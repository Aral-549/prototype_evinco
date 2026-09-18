"""SegFormer (MiT-B0) reconstructed to match the shipped `best_segformer_b0` weights.

Why this file exists
--------------------
The checkpoint `best_segformer_b0.pth` stores its tensors under a custom module
layout (`segformer.stages.N.blocks.M.attention.q_proj`, ...) that matches neither
`segmentation_models_pytorch` nor HuggingFace's `SegformerForSemanticSegmentation`
(which uses `segformer.encoder.block.N.M.attention.self.query`). With no matching
architecture in the repository, pointing `MODEL_CHECKPOINT_PATH` at it caused the
fail-safe to silently fall back to the old U-Net: the system kept running, reported
`is_fallback: True`, and served the weaker model.

The layout is fully determined by the tensor shapes, and it is a textbook MiT-B0:

    embed dims   [32, 64, 160, 256]
    depths       [2, 2, 2, 2]
    SR ratios    [8, 4, 2, 1]        (spatial reduction in efficient attention)
    MLP ratio    4
    heads        [1, 2, 5, 8]        (head dim 32 throughout, the MiT-B0 convention)
    decode head  4 x linear proj -> 256, fuse, BN, 1-channel classifier

Module and attribute names below are chosen to reproduce those state-dict keys
exactly, so the weights load with `strict=True`. That strictness is deliberate: a
silent partial load would leave randomly-initialised layers in an evidentiary model.
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class OverlapPatchEmbed(nn.Module):
    """Overlapping patch embedding: strided conv, flatten, layer norm."""

    def __init__(self, in_ch, out_ch, patch, stride, padding):
        super().__init__()
        self.proj = nn.Conv2d(in_ch, out_ch, kernel_size=patch, stride=stride,
                              padding=padding)
        self.layer_norm = nn.LayerNorm(out_ch)

    def forward(self, x):
        x = self.proj(x)
        _, _, h, w = x.shape
        x = x.flatten(2).transpose(1, 2)   # (B, HW, C)
        return self.layer_norm(x), h, w


class SequenceReduction(nn.Module):
    """Spatial reduction before key/value projection (the 'efficient' in Efficient Attention).

    Reduces the K/V sequence length by `ratio^2`, which is what makes attention
    affordable at the high resolutions SAR tiles need.
    """

    def __init__(self, dim, ratio):
        super().__init__()
        self.sequence_reduction = nn.Conv2d(dim, dim, kernel_size=ratio, stride=ratio)
        self.layer_norm = nn.LayerNorm(dim)

    def forward(self, x, h, w):
        b, n, c = x.shape
        x = x.transpose(1, 2).reshape(b, c, h, w)
        x = self.sequence_reduction(x)
        x = x.reshape(b, c, -1).transpose(1, 2)
        return self.layer_norm(x)


class EfficientAttention(nn.Module):
    def __init__(self, dim, num_heads, sr_ratio):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.scale = self.head_dim ** -0.5

        self.q_proj = nn.Linear(dim, dim)
        self.k_proj = nn.Linear(dim, dim)
        self.v_proj = nn.Linear(dim, dim)
        self.o_proj = nn.Linear(dim, dim)

        self.sequence_reduction = (
            SequenceReduction(dim, sr_ratio) if sr_ratio > 1 else None
        )

    def _heads(self, t, b, n):
        return t.reshape(b, n, self.num_heads, self.head_dim).transpose(1, 2)

    def forward(self, x, h, w):
        b, n, c = x.shape
        q = self._heads(self.q_proj(x), b, n)

        kv_in = self.sequence_reduction(x, h, w) if self.sequence_reduction else x
        m = kv_in.shape[1]
        k = self._heads(self.k_proj(kv_in), b, m)
        v = self._heads(self.v_proj(kv_in), b, m)

        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(b, n, c)
        return self.o_proj(out)


class DWConv(nn.Module):
    """Depthwise 3x3 inside the MLP: SegFormer's replacement for positional encoding."""

    def __init__(self, dim):
        super().__init__()
        self.dwconv = nn.Conv2d(dim, dim, 3, padding=1, groups=dim)

    def forward(self, x, h, w):
        b, n, c = x.shape
        x = x.transpose(1, 2).reshape(b, c, h, w)
        x = self.dwconv(x)
        return x.flatten(2).transpose(1, 2)


class MixFFN(nn.Module):
    def __init__(self, dim, hidden):
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.dwconv = DWConv(hidden)
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x, h, w):
        x = self.fc1(x)
        x = F.gelu(self.dwconv(x, h, w))
        return self.fc2(x)


class Block(nn.Module):
    def __init__(self, dim, num_heads, sr_ratio, mlp_ratio=4):
        super().__init__()
        self.layernorm_before = nn.LayerNorm(dim)
        self.attention = EfficientAttention(dim, num_heads, sr_ratio)
        self.layernorm_after = nn.LayerNorm(dim)
        self.mlp = MixFFN(dim, dim * mlp_ratio)

    def forward(self, x, h, w):
        x = x + self.attention(self.layernorm_before(x), h, w)
        x = x + self.mlp(self.layernorm_after(x), h, w)
        return x


class Stage(nn.Module):
    def __init__(self, in_ch, dim, depth, num_heads, sr_ratio, patch, stride, padding):
        super().__init__()
        self.patch_embeddings = OverlapPatchEmbed(in_ch, dim, patch, stride, padding)
        self.blocks = nn.ModuleList(
            [Block(dim, num_heads, sr_ratio) for _ in range(depth)])
        self.layer_norm = nn.LayerNorm(dim)

    def forward(self, x):
        x, h, w = self.patch_embeddings(x)
        for blk in self.blocks:
            x = blk(x, h, w)
        x = self.layer_norm(x)
        b, _, c = x.shape
        return x.transpose(1, 2).reshape(b, c, h, w)


class MixTransformer(nn.Module):
    """The MiT encoder. Returns the four stage feature maps."""

    def __init__(self, in_channels=3, dims=(32, 64, 160, 256), depths=(2, 2, 2, 2),
                 heads=(1, 2, 5, 8), sr_ratios=(8, 4, 2, 1)):
        super().__init__()
        cfg = [
            (in_channels, dims[0], 7, 4, 3),
            (dims[0], dims[1], 3, 2, 1),
            (dims[1], dims[2], 3, 2, 1),
            (dims[2], dims[3], 3, 2, 1),
        ]
        self.stages = nn.ModuleList([
            Stage(ic, dim, depths[i], heads[i], sr_ratios[i], p, s, pad)
            for i, (ic, dim, p, s, pad) in enumerate(cfg)
        ])

    def forward(self, x):
        feats = []
        for stage in self.stages:
            x = stage(x)
            feats.append(x)
        return feats


class LinearProjection(nn.Module):
    def __init__(self, in_dim, out_dim):
        super().__init__()
        self.proj = nn.Linear(in_dim, out_dim)

    def forward(self, x):
        b, c, h, w = x.shape
        x = x.flatten(2).transpose(1, 2)
        x = self.proj(x)
        return x.transpose(1, 2).reshape(b, -1, h, w)


class SegFormerHead(nn.Module):
    """All-MLP decoder: project every stage to a common width, upsample, fuse."""

    def __init__(self, dims=(32, 64, 160, 256), embed_dim=256, num_classes=1):
        super().__init__()
        self.linear_projections = nn.ModuleList(
            [LinearProjection(d, embed_dim) for d in dims])
        # No bias key in the checkpoint for linear_fuse.
        self.linear_fuse = nn.Conv2d(embed_dim * len(dims), embed_dim, 1, bias=False)
        self.batch_norm = nn.BatchNorm2d(embed_dim)
        self.classifier = nn.Conv2d(embed_dim, num_classes, 1)

    def forward(self, feats):
        target = feats[0].shape[2:]
        projected = []
        for proj, f in zip(self.linear_projections, feats):
            x = proj(f)
            if x.shape[2:] != target:
                x = F.interpolate(x, size=target, mode='bilinear', align_corners=False)
            projected.append(x)

        # Concatenated high-to-low so the fuse weights see the stages in the order
        # they were trained in.
        x = self.linear_fuse(torch.cat(projected[::-1], dim=1))
        x = F.relu(self.batch_norm(x))
        return self.classifier(x)


class SegFormer(nn.Module):
    """SegFormer-B0 for binary segmentation, emitting full-resolution logits."""

    def __init__(self, in_channels=3, num_classes=1):
        super().__init__()
        self.segformer = MixTransformer(in_channels=in_channels)
        self.decode_head = SegFormerHead(num_classes=num_classes)

    def forward(self, x):
        size = x.shape[2:]
        logits = self.decode_head(self.segformer(x))
        # The head works at stride 4; restore the input resolution so the rest of
        # the pipeline sees the same contract as the U-Net.
        return F.interpolate(logits, size=size, mode='bilinear', align_corners=False)

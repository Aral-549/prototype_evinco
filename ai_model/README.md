# AI / ML Subsystem (Deep Learning & Evaluation)
### MarSlick | SIH Problem Statement ID: 26143

This directory houses the neural network weights, model metadata sidecars, ground-truth SAR calibration imagery, and the automated validation gate scripts.

---

## Directory Architecture

```
ai_model/
├── weights/
│   └── best_unet_dice_0.8018/
│       ├── best_unet           # PyTorch model weights (31,043,521 parameters)
│       └── model_info.json     # Architecture specs, Dice score (0.8018), normalization settings
├── calibration_data/
│   └── known_sar_spill.jpg     # Ground-truth SAR image with confirmed oil slick for calibration
├── scripts/
│   └── validate_checkpoint.py  # 6-step validation gate & side-by-side behavioral comparator
└── README.md                   # ML developer instructions
```

---

## Model Hot-Swap Protocol

When new trained model weights arrive:

### Step 1: Place Weights and Metadata
Create a new folder under `ai_model/weights/`:
```bash
ai_model/weights/<new_model_name>/
├── model.pt (or model.pth)
└── model_info.json
```

### Step 2: Run the 6-Step Validation Gate
```bash
source .venv/bin/activate
cd backend
python manage.py validate_model --checkpoint ../ai_model/weights/<new_model_name>/model.pt
```
*What the validation gate checks:*
1. Model metadata sidecar presence and valid schema
2. Weight parameter tensor integrity
3. 256x256x3 single-tile tensor I/O contract
4. Full-scene tiled inference and boundary stitching
5. Side-by-side behavioral comparison against baseline on real SAR imagery
6. Overall hot-swap readiness assessment

### Step 3: Activate in Production
In `backend/.env`:
```env
MODEL_CHECKPOINT_PATH=../ai_model/weights/<new_model_name>/model.pt
```
Restart the Celery worker. Zero API, zero database, and zero frontend code changes are required.

---

## Assigned AI/ML Role

- **AI/ML Engineer (Model Optimization):** Hot-swap candidate checkpoints, implement false positive look-alike suppression (GLCM texture analysis and low-wind calm sea gating), and calculate Bonn Agreement oil volume estimates ($m^3$).

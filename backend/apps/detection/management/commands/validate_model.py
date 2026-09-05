from django.core.management.base import BaseCommand
from django.conf import settings
from scripts.validate_checkpoint import validate_checkpoint


class Command(BaseCommand):
    help = "Run the Oil Spill Model Checkpoint Validation Gate on a target checkpoint."

    def add_arguments(self, parser):
        parser.add_argument(
            '--checkpoint',
            type=str,
            default=str(getattr(settings, 'MODEL_CHECKPOINT_PATH', settings.UNET_CHECKPOINT)),
            help="Path to checkpoint directory or file (.pt / .pth)",
        )

    def handle(self, *args, **options):
        checkpoint = options['checkpoint']
        success = validate_checkpoint(checkpoint)
        if not success:
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Validation gate passed."))

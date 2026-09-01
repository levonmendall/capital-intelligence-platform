"""Process-local Python startup hooks for production runtime repairs."""

from provider_preselection_checkpoint_bootstrap import install_for_epoch_provider_child

# This is deliberately inert for every process except
# ``python -m operations.epoch_scoped_provider_acquisition`` provider children.
install_for_epoch_provider_child()

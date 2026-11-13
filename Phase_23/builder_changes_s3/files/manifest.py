# Frozen manifest for SeedSigner ESP32-S3 firmware.
# Freezes stdlib, embit, urtypes, and Phase 23 headless signer modules.
include("$(PORT_DIR)/boards/manifest.py")

require("logging")

module("hmac.py", base_path="$(MPY_DIR)/../../../deps/third-party")
package("urtypes", base_path="$(MPY_DIR)/../../../deps/third-party")
module("hashlib.py", base_path="$(MPY_DIR)/../../../deps/third-party")
module("seedsigner_lvgl_screens.py", base_path="$(MPY_DIR)/../../../deps/third-party")

try:
    package("seedsigner", base_path="$(MPY_DIR)/../../../frozen_app")
    package("embit", base_path="$(MPY_DIR)/../../../frozen_app")
    module("seedsigner_frozen_build.py", base_path="$(MPY_DIR)/../../../frozen_app")
    module("_headless_fixtures.py", base_path="$(MPY_DIR)/../../../frozen_app")
    module("_headless_signer.py", base_path="$(MPY_DIR)/../../../frozen_app")
except OSError:
    pass

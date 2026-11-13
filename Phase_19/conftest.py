"""pytest-embedded options for the SeedSigner stateless bootloader suite.

--canary: run the Phase 19 warm-reset canary campaign (control REMANENT
then patched CLEARED). Requires the canary_scrub payload on the SD card
as seedsigner_esp32p4.bin / seedsigner_esp32s3.bin. Off by default so
normal CI (MicroPython payload) is unaffected.
"""


def pytest_addoption(parser):
    parser.addoption(
        "--canary",
        action="store_true",
        default=False,
        help="Run Phase 19 canary scrub campaign (needs canary payload on SD)",
    )

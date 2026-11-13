import gc
import vfs
from flashbdev import bdev

try:
    if bdev:
        vfs.mount(bdev, "/")
except OSError:
    pass

gc.collect()

try:
    import _headless_signer
    _headless_signer.run()
except ImportError:
    pass

"""Atomic XML persistence shared by the CRM and legacy memory commands."""

import os
from pathlib import Path
import tempfile

from app_config import validate_production_memory


def write_memory(path: Path, content: bytes, *, production=False, create=False) -> bool:
    with tempfile.NamedTemporaryFile('wb', delete=False, dir=path.parent) as output:
        temporary = Path(output.name)
        try:
            output.write(content)
            output.close()
            if production:
                validate_production_memory(path)
            if create:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    return False
            else:
                os.replace(temporary, path)
            return True
        finally:
            temporary.unlink(missing_ok=True)

"""Run the reviewed offline suite; deliberately exclude side-effectful test_fetch.py.

Run with .venv-arm64/bin/python -B run_safe_tests.py.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()


def safety_guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
        raise RuntimeError('Network access is forbidden in the offline suite')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).resolve()
        temporary = path.is_relative_to(TEMP_ROOT) and not path.is_relative_to(ROOT)
        if not temporary and (path.suffix.lower() == '.xml' or path.name.startswith('.env')):
            raise RuntimeError('Production configuration or XML access is forbidden in tests')
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
        if writing and not temporary:
            raise RuntimeError('Tests may write only temporary files')


def main():
    sys.dont_write_bytecode = True
    sys.addaudithook(safety_guard)
    # Load the real libraries before older tests try to install import stubs.
    import telegram.ext
    import openai
    names = [
        'test_agent_profile', 'test_bot_client_import', 'test_bot_daily_brief',
        'test_bot_email_draft', 'test_bot_safe_client_actions', 'test_bot_tour',
        'test_bot_voice_parser', 'test_client_importer', 'test_client_manager',
        'test_client_reference', 'test_daily_brief', 'test_email_generator',
        'test_email_sender', 'test_tour', 'test_stabilization', 'test_crm_logging', 'test_natural_crm', 'test_followup_queries', 'test_telegram_crm_dispatch', 'test_voice_draft_diagnostics', 'test_environment_isolation',
    ]
    # No credentials inherited from the invoking shell.
    clean_env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR') if k in os.environ}
    clean_env['APP_ENV'] = 'testing'
    with patch.dict(os.environ, clean_env, clear=True):
        suite = unittest.defaultTestLoader.loadTestsFromNames(names)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())

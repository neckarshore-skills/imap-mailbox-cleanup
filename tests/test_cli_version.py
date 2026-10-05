from click.testing import CliRunner

import mailbox_cleanup
from mailbox_cleanup.cli import cli


def test_version_flag_prints_the_package_version():
    # Regression: after the distribution was renamed to mailbox-autopilot, click could
    # no longer infer the package from the module name and --version raised.
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0, result.output
    assert mailbox_cleanup.__version__ in result.output

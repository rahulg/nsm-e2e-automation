import os


def pytest_addoption(parser):
    parser.addoption(
        "--env",
        default="qa",
        choices=["qa", "stage"],
        help="Target environment to run tests against (default: qa)",
    )


def pytest_configure(config):
    os.environ["NSM_ENV"] = config.getoption("--env", default="qa")

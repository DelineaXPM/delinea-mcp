# Repository Guidelines

- Run `pytest -q` and ensure all tests, including the integration suite, pass before committing.
- Add tests for any new functionality, including integration coverage where applicable.
- The integration tests in `tests/integration` rely on environment variables providing credentials for the real Delinea API. Configure these variables when executing the suite.
- Update `config.json` with your local values when running the server manually for testing.

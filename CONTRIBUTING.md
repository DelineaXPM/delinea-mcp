# Contributing

While you can use python without `uv`, this project recommends it as the primary way to interact with the project to simplify dependency management and virtual environment setup.

> uv provides a drop-in replacement for common pip, pip-tools, and virtualenv commands.

## UV Commands

- `uv pip sync requirements.txt`: Install dependencies from `uv.lock` into a virtual environment.
- `uv export --format requirements-txt --no-hashes > requirements.txt` : Export dependencies to a `requirements.txt` file.
- [Universal Resolution](https://docs.astral.sh/uv/concepts/resolution/#universal-resolution)
- [Locking Dependencies](https://docs.astral.sh/uv/pip/compile/#locking-requirements)

## Inspector

Run the MCP Inspector (requires Node.js/npm).

```shell
# Run the MCP Inspector UI which will launch the server using uv
npx @modelcontextprotocol/inspector
```

## Tooling

Prior to any completion of work, ensure code linting and formatting is applied with the `trunk` tool.

You can install with: `curl https://get.trunk.io -fsSL | bash -s -- -y`.

For windows usage, this should be run in `git bash` or `wsl2` or it will fail.

## Pull Request Title

[Use conventional commit](https://www.conventionalcommits.org/en/v1.0.0/) for pull request titles to keep it consistent and pass the PR check.

# Contributing

While you can use python without `uv`, this project recommends as the primary way to interacting to simplify dependency management and virtual environment setup.

> uv provides a drop-in replacement for common pip, pip-tools, and virtualenv commands.

## UV Commands

- To lock dependencies declared in a pyproject.toml: `uv pip compile pyproject.toml --universal -o requirements.txt`
  - [Universal Resolution](https://docs.astral.sh/uv/concepts/resolution/#universal-resolution)
  - [Locking Dependencies](https://docs.astral.sh/uv/pip/compile/#locking-requirements)

## Inspector

Run the MCP Inspector (requires Node.js/npm).

```shell
# Run the MCP Inspector UI which will launch the server using uv
npx @modelcontextprotocol/inspector
```

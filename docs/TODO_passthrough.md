# Passthrough Authentication Design (Future)

The `passthrough` auth mode will allow clients to supply an existing Delinea Secret Server token in the `Authorization` header. The MCP server will introspect this token via the Delinea API and map returned claims to MCP scopes. Implementation of this flow is slated for a future release.


from .service import Authenticator, Remote


def create_mcp(application, credentials, token, remote=None):
    from mcp.server.fastmcp import FastMCP

    if remote:
        dispatch = Remote(remote, token).dispatch
    else:
        principal = Authenticator(credentials).authenticate(token)
        if principal is None:
            raise PermissionError("invalid MCP credential")

        def dispatch(operation, params):
            return application.dispatch(operation, params, principal)

    server = FastMCP("SageKit")

    @server.tool()
    def snapshot() -> dict:
        """Pin the current corpus revision."""
        return dispatch("snapshot", {})

    @server.tool()
    def list_knowledge(revision: str | None = None) -> list[dict]:
        """List records visible to the configured identity."""
        return dispatch("list", {"revision": revision})

    @server.tool()
    def add_knowledge(record: dict) -> dict:
        """Append a sourced knowledge record."""
        return dispatch("add", {"record": record})

    @server.tool()
    def search_knowledge(query: str, revision: str | None = None, limit: int = 10,
                         context: dict | None = None) -> list[dict]:
        """Find exact and semantically related source evidence."""
        params = {"query": query, "revision": revision, "limit": limit}
        if context is not None:
            params["context"] = context
        return dispatch("query", params)

    @server.tool()
    def decide(request: dict, revision: str | None = None) -> dict:
        """Ask a typed Choice, Score or Noul question."""
        return dispatch("decide", {"request": request, "revision": revision})

    @server.tool()
    def check_gate(policy: dict, pin: dict | None = None) -> dict:
        """Check the pinned corpus at a contextual verification gate."""
        return dispatch("gate-check", {"policy": policy, "pin": pin})

    @server.tool()
    def record_approval(approval: dict) -> dict:
        """Record an authorized choice in the outcome ledger."""
        return dispatch("approve", approval)

    @server.tool()
    def record_outcome(observation: dict) -> dict:
        """Record a measured utility linked to an independently verified change."""
        return dispatch("observe", observation)

    @server.tool()
    def promote_verified_change(receipt: dict) -> dict:
        """Publish an authenticated, independently verified successful change."""
        return dispatch("promote", {"receipt": receipt})

    return server

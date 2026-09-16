# Getting Started

## Host runtime (no device required)

Requires Python 3 (standard library only).

```bash
python3 run_all_tests.py     # runs the offline unit suite; must be fully green
```

The host runtime is `phoneharness_agent.py`. It talks to a device MCP endpoint
over HTTP and authenticates with the `PHONEHARNESS_MCP_TOKEN` environment
variable.

## Device runtime

The device side builds with Theos:

```bash
make package THEOS_PACKAGE_SCHEME=roothide   # or rootless
```

Building the optional helper tools (`mcp-root`, `mcp-roothelper`, `mcp-logreader`,
`mcp-ldid`) additionally requires external third-party sources that are not
vendored here — see `DEPENDENCIES.md`.

## Using the MCP surface

Import the Postman collection in `postman/` and point `baseUrl` at your device
endpoint. All requests must send the `X-MCP-Token` header.

## Safety

Only automate devices you own or are explicitly authorized to control. See
`SECURITY.md`.

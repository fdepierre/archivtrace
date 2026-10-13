# CI helpers

Historically GitHub Actions used a stub under `ci/ollama_shared` because the
package lived only as a sibling checkout (`../shared/ollama_shared`).

**Current install path:** the Ollama client is vendored at
`vendor/ollama_shared` and installed via `requirements.txt`
(`pip install -e ./vendor/ollama_shared`). CI and local clones share the same
contract.

The `ci/ollama_shared` directory remains as a thin compatibility stub for older
docs/scripts; prefer `vendor/ollama_shared`.

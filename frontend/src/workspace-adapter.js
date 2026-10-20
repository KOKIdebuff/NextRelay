/**
 * Presentation/intent port, not an HTTP API contract.
 * A future T11 adapter must implement this boundary with real permissions,
 * version checks and server results. This prototype only supplies SyntheticAdapter.
 */
export class WorkspaceAdapter {
  async read() { throw new Error('请提供展示适配器'); }
  async submit(_intent) { throw new Error('请提供操作意图适配器'); }
}

/**
 * Presentation/intent port, not an HTTP API contract.
 * LocalAdapter uses authenticated same-origin business services; SyntheticAdapter
 * remains an explicitly separate in-memory prototype. Neither may fall back to the other.
 */
export class WorkspaceAdapter {
  async read() { throw new Error('请提供展示适配器'); }
  async submit(_intent) { throw new Error('请提供操作意图适配器'); }
}

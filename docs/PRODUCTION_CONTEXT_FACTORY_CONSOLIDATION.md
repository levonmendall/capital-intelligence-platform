# Production-context factory consolidation

The persisted-context and executable-context provider factories now use one canonical
store and environment-resolution helper. Provider behavior remains separate: the
runtime subclass still owns publication-timing semantics, while database paths,
portfolio code, code version, and store construction can no longer drift between the
two factories.

No decision, evidence, construction, execution, or portfolio authority changed. The
final branch remains subject to complete release, desktop/iPhone browser, historical,
provider, paper-readiness, and security validation before merge.

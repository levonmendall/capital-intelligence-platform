# Explicit Streamlit entrypoints

The production presentation path uses ordinary Python imports and explicit function calls.

- `render_app.py` invokes the authenticated entrypoint.
- `secure_app.py` authenticates the principal and supplies session-local portfolio access functions.
- `app.py` installs presentation compatibility adapters and invokes the four-surface renderer.
- `app_impl.py` renders Today, Environment, Portfolio, and History and receives authorized portfolio functions explicitly.

The entrypoints do not read, rewrite, compile, or execute another Python source file at runtime. This keeps authentication and portfolio authorization explicit while preserving the canonical CIO, construction, paper-execution, and real-money-disabled boundaries.

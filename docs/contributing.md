# Contributing to Xpdite

Thank you for your interest in contributing to Xpdite. This document outlines the process for contributing and our expectations.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/your-username/xpdite.git
   cd xpdite
   ```
3. Install dependencies:
   ```bash
   bun install
   bun run install:python
   ```
4. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Workflow

1. Make your changes following the [Development Guide](./development.md)
2. Test your changes locally with `bun run dev`
3. Ensure the build succeeds: `bun run build`
4. Commit with a clear, descriptive message
5. Push to your fork and open a Pull Request

## Areas for Contribution

### High Priority

- **macOS Support** - Porting the screenshot system and DPI handling
- **MCP Server Implementations** - Completing the Discord and Canvas servers (Gmail/Calendar are now active)
- **Test Coverage** - Unit and integration tests for both Python and React
- **Accessibility** - Keyboard navigation, screen reader support

### Medium Priority

- **UI/UX Improvements** - Better theming, animations, responsive design
- **Documentation** - Tutorials, examples, video guides
- **Performance** - Optimizing streaming, reducing memory usage
- **Error Handling** - Better error messages and recovery flows

### Good First Issues

- Adding new demo MCP tools
- Improving CSS styling
- Adding TypeScript interfaces for untyped code
- Writing documentation for specific features

## Code Style

### Python

- Follow PEP 8 conventions
- Use type hints for all function parameters and return values
- Write docstrings for public functions and classes
- Use async/await for I/O-bound operations

### TypeScript / React

- Use functional components with hooks
- Define interfaces in `src/ui/types/index.ts`
- Follow the existing component structure (pages, components, hooks)
- Use CSS modules or component-scoped CSS files

### Commit Messages

Write clear, concise commit messages:

```
feat: add web search MCP server with DuckDuckGo integration
fix: resolve DPI scaling on multi-monitor Windows setups
refactor: extract screenshot logic into separate service module
docs: add MCP integration guide
```

Prefix with: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`

## Pull Request Process

1. **Description**: Clearly describe what your PR does and why
2. **Scope**: Keep PRs focused on a single feature or fix
3. **Testing**: Describe how you tested your changes
4. **Screenshots**: Include before/after screenshots for UI changes
5. **Breaking Changes**: Clearly note any breaking changes

## Adding MCP Servers

If you're implementing one of the placeholder MCP servers (Gmail, Calendar, Discord, Canvas):

1. Follow the [MCP Guide](./mcp-guide.md) for the implementation pattern
2. Handle authentication securely (never commit credentials)
3. Write tool descriptions that are clear and specific for the LLM
4. Add error handling that returns user-friendly messages
5. Update `mcp_servers/config/servers.json` with your server
6. Update the documentation

## Reporting Issues

When reporting issues, please include:

- **Description**: What happened vs. what you expected
- **Steps to Reproduce**: Minimal steps to trigger the issue
- **Environment**: OS version, Python version, Node.js version, Ollama version
- **Logs**: Relevant console output from both the Python server and Electron
- **Screenshots**: If applicable

## Code of Conduct

- Be respectful and constructive in all interactions
- Focus on the technical merits of contributions
- Welcome newcomers and help them get started
- Credit others' work appropriately

## License

By contributing, you agree that your contributions will be licensed under the same license as the project.

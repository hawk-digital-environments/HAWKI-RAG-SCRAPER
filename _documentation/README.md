# CustomCrawler Documentation

Welcome to the CustomCrawler documentation. This project contains a Python crawler service, Docker support, profile-driven crawl configuration, and a SvelteKit admin UI for monitoring jobs and managing crawler profiles.

## Documentation Structure

### [API Reference](./API_REFERENCE.md)
Complete API endpoint documentation including:
- Request/response schemas
- Parameter descriptions
- Example requests and responses
- Error handling
- SvelteKit UI proxy endpoints used by the frontend

### [Architecture](./ARCHITECTURE.md)
System design and technical architecture:
- Component overview
- Data flow
- Class diagrams
- Design patterns
- Technology stack
- UI route and component responsibilities
- UI-to-backend data mapping

### [Deployment Guide](./DEPLOYMENT.md)
Production deployment instructions:
- Docker deployment
- Kubernetes deployment
- Systemd service setup
- Nginx reverse proxy configuration
- SSL/TLS setup
- Monitoring and logging

### [Configuration Guide](./CONFIGURATION.md)
Advanced configuration options:
- Environment variables
- Rate limiting strategies
- Performance tuning
- Custom extractors
- Browser configuration

### [Developer Guide](./DEVELOPER_GUIDE.md)
Contributing and extending the service:
- Development setup
- Code structure
- Starting the SvelteKit UI with `make start-ui`
- Adding new features
- Testing guidelines
- Best practices

### Refactoring Notes
- [Refactoring Guide](./REFACTORING_GUIDE.md): Migration steps and rationale
- [Refactoring Summary](./REFACTORING_SUMMARY.md): High-level overview of changes

## Quick Links

- [Main README](../README.md)
- [UI README](../ui/README.md)
- [Makefile](../Makefile)

## Getting Help

- Check the [FAQ](../README.md#faq) in the main README
- Review the [Troubleshooting](../README.md#troubleshooting) section
- Open an issue on the project repository

## Version

Documentation version: 2.0.0
Last updated: 2026-05-11

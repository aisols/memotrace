# Repository Tools

Reserve this directory for tools that coordinate multiple components, such as
controlled contract-snapshot updates or whole-system verification. No tool is
implemented yet.

Do not put application libraries or mandatory component build logic here.
Component-specific commands must live with their component and work after it is
extracted into a standalone repository. Repository-wide convenience commands
may delegate to those documented entry points.

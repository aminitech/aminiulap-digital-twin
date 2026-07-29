# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

Report privately through GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on this repository. That channel is
enabled and goes to the maintainers directly.

<!-- TODO before publishing: add a monitored security contact address here,
     e.g. security@amini.ai, and confirm private vulnerability reporting is
     enabled in the repository settings. -->

We aim to acknowledge a report within five working days.

## Scope

This is research software: a geospatial and radio-propagation simulation
pipeline. It is not a hosted service and holds no user accounts or credentials.
The security concerns that are in scope:

- Code execution risks in the pipeline stages, particularly deserialisation of
  scene, config, or shapefile inputs from an untrusted source
- Path traversal or arbitrary write via `study.toml` or environment-variable
  configuration
- Dependency vulnerabilities in the pinned environments
- Accidental disclosure of credentials or non-public data in the repository or
  its history

## Out of scope

- Vulnerabilities in Blender, Mitsuba, Sionna, or GDAL themselves. Report those
  upstream. We will help route a report if you are unsure where it belongs.
- The security of any data you supply. See [DATA.md](DATA.md) — this repository
  ships no geospatial data, and you are responsible for the handling and
  classification of layers you obtain yourself.

## Sensitive geospatial data

This repository deliberately ships no geospatial data. If you believe a commit,
figure, or render in this repository discloses sensitive infrastructure geometry
or attributes, please report it through the private channel above rather than
opening an issue. We treat that as a security report, not a documentation bug.

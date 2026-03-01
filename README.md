# Tigo Energy

Custom Home Assistant integration for Tigo Energy cloud data (Premium API).

## Project Status

Scaffolded repository. Core integration code is not implemented yet.

## Initial Goals

- Build a clean config flow in Home Assistant UI
- Authenticate against Tigo cloud API
- Expose practical system and module telemetry as entities
- Ship as a custom integration first, then publish via HACS

## Planned Repository Structure

```text
custom_components/tigo_energy/
  __init__.py
  manifest.json
  config_flow.py
  coordinator.py
  sensor.py
  const.py
  api.py
  translations/en.json
```

## Development Notes

- Primary install target (first phase): manual install on your own HA instance
- HACS packaging/metadata will be added once the integration is stable

## License

License to be added.

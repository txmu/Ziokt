# Ziokt Tri Computer

Offline friendly ternary computer simulator PWA. It runs locally in the browser and does not need an API key or external script host. Assembly files and snapshots stay in the browser unless the operator exports them.

## Development

```sh
npm ci
npm run build
```

The development server binds to loopback. Production assets are served below `/tri/` by the Ziokt static application host.

## Encrypted federation exchange

Use `ziokt companion tri put` to package an assembly program and optional JSON machine snapshot in the local SafeFS vault. Use `ziokt companion tri publish` with a bridge configured for the `tri` application to publish the sealed object as a signed community file. `ziokt companion tri get` authenticates and restores the project to a private output file. Imported projects are data; the adapter does not execute them.

The instruction reference contains English and Simplified Chinese descriptions. Federation signatures and object digests remain language independent.

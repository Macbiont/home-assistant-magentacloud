# Contributing

Bug reports and pull requests are welcome. Before opening an issue, search for
an existing report and remove credentials, email addresses, file names, backup
contents, and other personal data from logs or screenshots.

Run the checks from the repository root:

```sh
python3 -m unittest discover -s tests -v
docker run --rm --network none --memory 2g --cpus 2 --entrypoint python \
  -v "$PWD:/work:ro" ghcr.io/home-assistant/home-assistant:2026.9.3 \
  /work/testenv/test_backup_runtime.py
docker run --rm --network none --memory 2g --cpus 2 --entrypoint python \
  -v "$PWD:/work:ro" ghcr.io/home-assistant/home-assistant:2026.9.3 \
  /work/testenv/runtime_outage.py
```

New behavior should include focused tests. Changes must preserve config-entry
and entity unique IDs unless a documented migration is included.

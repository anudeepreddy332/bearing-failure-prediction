# Set 3 Source Intake Boundary

## Status

Phase F recovered and registered the ignored local package
`data/raw/set3/3rd_test.rar` from a user-downloaded outer `IMS.zip` archive. The outer
archive was deleted only after byte-verified recovery. Its hash, selected member path,
CRC, deletion proof, package hash, and metadata-only inner index are preserved in
`data/manifests/ims_sets23_source_packages/v1/`.

This is source acquisition and registration only. Set 3 has not been extracted into
recordings, parsed, assigned identities/outcomes, featured, evaluated, pooled, or used by
any model or serving path.

## Evidence Boundary

The selected outer member was named `IMS/3rd_test.rar`. Its metadata-only inner index has
the observed root `4th_test/txt`. This naming discrepancy is recorded as an unresolved
provenance limitation, not interpreted as a dataset-role or outcome claim. The inner
index uses `bsdtar` metadata listing only; encryption status is not independently
verified, and no signal payload is opened.

The local copy is not publisher-authenticated. A local SHA-256 proves only byte stability
after registration. License terms and original acquisition details are not independently
verified.

## Future Role

Set 3 is a conditional future external-holdout candidate. That role is not frozen and
does not authorize implementation. Any identity, outcome, feature, evaluation, or pooling
work requires a separate decision and explicit evidence gates. Phase E's Set 1 endpoint
proxy result remains `not_identifiable_shared_run_clock_target`; this source registration
does not authorize Set 2 or Set 3 use.

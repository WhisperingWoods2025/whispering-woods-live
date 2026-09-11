# Lawn-tree demonstration scan

- Creator: Charin Rungchaowarat (promc / promto-c).
- Source: https://huggingface.co/datasets/promc/reconstruction-scenes
- Original: lawn-tree/gsplat/lawn-tree.ply (205 source photographs, per dataset card).
- Publisher licence: CC0-1.0, https://creativecommons.org/publicdomain/zero/1.0/
- Original SHA256: 56f8a6a9cf0a82f0d087cb3c0e1fb241856857aa75c17f160399eec6a5f8fd05
- Retrieved: 2026-09-11.

This is an external captured scene, NOT Berchtesgaden or a georeferenced inventory tree. Capture date and metric scale have not been verified. It must not be used for measurements, forest health assessment, or forecast validation.

## Local preparation

Tool: @playcanvas/splat-transform 3.4.2 (MIT).
No remote processing, model training, billable API, or cloud storage was used.

1. Remove invalid splats and view-dependent spherical harmonics.
2. Merge/simplify to 250,000 splats using the tool's uniform decimation.
3. Crop to source-coordinate box (-6,-8,-6) to (6,3,6), removing distant reconstruction outliers.
4. Convert to SPZ version 3. Final count: 232,328 splats.

Commands (large source/intermediates are not deployed):

```text
node cli.mjs lawn-tree-source.ply --filter-nan --filter-harmonics 0 --decimate 250000 lawn-tree-web.ply
node cli.mjs lawn-tree-web.ply --filter-box=-6,-8,-6,6,3,6 --spz-version 3 lawn-tree.spz
```

Display rotates 180 degrees around X and fits the cropped scene. Cropping, simplification, and removal of directional colour can reduce fidelity. The low-power option lowers pixel density and frame rate; it does not alter the underlying scan or provide a separate resolution dataset.

Spark 2.1.0 and Three.js 0.180.0 render on the visitor's device. The compressed asset is fetched only when the Tree scan workspace is opened. It does not contact Earth Engine or weather APIs.


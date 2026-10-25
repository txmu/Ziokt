# Official ALFS validation

The pinned official book and kernel finished compiling in
[run 40165019881](https://github.com/txmu/Ziokt/actions/runs/40165019881).
Image preparation then failed because `sudo mkdir` left `images/` owned by
root and the runner could not `truncate` `rootfs.ext4`. Only build logs were
retained, so that run supplies compilation evidence, not a reusable image or
an ALFS QEMU boot result.

`image.sh` assigns the image directory to the runner before image creation.
`check_image.sh` reproduces the root-owned directory, runs the same production
packaging commands on a 32 MiB fixture, checks the ext4 filesystem, and reads
back its copied release marker. It downloads and compiles nothing.

Push CI runs this packaging regression and the kernel-default adaptation test.
The several-hour official build and serial boot remain available by manually
dispatching `openci-alfs.yml` with `full_build=true`. A passing packaging job
does not assert that the official ALFS guest has booted. v1.0 node artifacts
and the independently validated Buildroot guests do not depend on an ALFS image.

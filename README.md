# VendorScheme
Generates diffusion MRI gradient table schemes compatible with scanner vendors

Currently only Siemens `.dvs` files can be created;
support for other vendors may be implemented in the future.

## Usage

```ShellSession
docker run -it --rm \
    -v $(pwd):/output \
    vendorscheme:latest \
    2 8 300 13 1000 24 3000 60 output.dvs
```

Inputs:

-   First argument is the number of blocks into which to split the scheme.
    If one intends to acquire all DWIs with a single execution of the scanner sequence,
    simply specify "1".
    A value of 2 is used where one intends to acquire half of the DWI volumes with one phase encoding direction,
    and th other half of the DWI volumes with the opposite phase encoding direction.
    The distribution of diffusion directions within each block will be relatively homogeneous,
    with maximal coverage achieved once the volumes are concatenated during pre-processing.

-   Second argument is the number of *b*=0 volumes to acquire.

-   Subsequent argument *pairs* encode a desired *b*-value
    and the total number of volumes to acquire within that *b*-value shell.

-   The final argument is an output file path.
    In some circumstances the command may split the input across multiple files,
    in which case it will append "`_1`", "`_2`" etc. to the filename stems.

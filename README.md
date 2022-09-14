
# AnimMUF

The program animmuf gets the MUF[^1] graphs from NOAA and generate a video animation.

##Config

The program's configuration file can be placed in `/etc`, in your home
directory or in the current directory.

```
---
target_dir: /tmp/muf
converter: /Users/fred/tmp/convert.sh
muf_file: /tmp/muf/muf_source.json
video_file: /tmp/muf/muf.mp4
font: /System/Library/Fonts/Supplemental/Arial Narrow.ttf
font_size: 16
```

## Converter

The converter converts an animated gif file into a mp4.
The following example uses ffmpeg for that operation.

```
#!/bin/bash

ffmpeg -y -i "$1" -movflags faststart -pix_fmt yuv420p -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" "$2"
```


[^1]: Maximum Usable Frequency

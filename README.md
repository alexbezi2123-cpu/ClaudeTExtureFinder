# ClaudeTextureFinder

Finds free PBR textures and bundles them into zip packs, one folder per texture.

Sources:

- **ambientCG** (https://ambientcg.com): CC0, uses the site's public JSON API.
- **TextureCan** (https://www.texturecan.com): experimental. It has no API, so the tool reads download links off the site's pages.

Only the Python 3 standard library is used, so there's nothing to install.

## Usage

Search without downloading:

```bash
python3 texturefinder.py search -q "mossy rock" -n 15
python3 texturefinder.py search -c Bricks -s Latest
python3 texturefinder.py search -t Decal Atlas -q leaves
```

Build a pack:

```bash
# 12 popular wood materials at 1K JPG
python3 texturefinder.py pack "Wood Starter" -q wood -n 12

# hand-picked ambientCG assets at 2K
python3 texturefinder.py pack "Castle Walls" --ids Bricks059,Rock030,PavingStones092 -r 2K

# decals and atlases, images only (drops .mtlx/.usdc extras)
python3 texturefinder.py pack "Foliage Decals" -t Decal Atlas -q leaf --images-only

# from a TextureCan category page
python3 texturefinder.py pack "TC Metal" --source texturecan --url https://www.texturecan.com/category/Metal/ -n 10
```

| Option | Meaning |
| --- | --- |
| `-q/--query` | search words |
| `-c/--category` | site category (Bricks, Wood, Metal, ...) |
| `-t/--type` | ambientCG types: Material, Decal, Atlas, HDRI, ... (default Material) |
| `-s/--sort` | Popular, Latest, Downloads, Alphabet |
| `-n/--limit` | max textures (default 20) |
| `-r/--res` | 1K, 2K, 4K, 8K (default 1K; falls back to the closest one available) |
| `-f/--format` | JPG or PNG |
| `--ids` | exact ambientCG asset ids, comma separated |
| `--images-only` | keep only the texture images |

## Output

Packs are written to `packs/<Pack_Name>.zip`:

```
Wood Starter/
  CREDITS.txt          source link + license for every texture
  Wood049/
    Wood049_1K-JPG_Color.jpg
    Wood049_1K-JPG_NormalGL.jpg
    Wood049_1K-JPG_Roughness.jpg
    ...
  Wood051/
    ...
```

Downloads are cached in `.cache/` (git-ignored), so rebuilding a pack doesn't download it again.

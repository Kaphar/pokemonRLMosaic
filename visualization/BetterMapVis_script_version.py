import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
from PIL import Image
from einops import rearrange
import requests
from multiprocessing import Pool
import io
import json
from tqdm import tqdm
import mediapy as media
import numpy as np

from v2.map_projection import project_position as _project_position


def make_all_coords_arrays(filtered_dfs):
    return np.array([tdf[['x', 'y', 'map']].to_numpy().astype(np.uint8) for tdf in filtered_dfs]).transpose(1,0,2)

def load_tex(name):
    resp = requests.get(sprites[name])
    return np.array(Image.open(io.BytesIO(resp.content)))

def get_sprite_by_coords(img, x, y):
    sy = 34+17*y
    sx = 9 +17*x
    alpha_v = np.array([255, 127,  39, 255], dtype=np.uint8)
    sprite = img[sy:sy+16, sx:sx+16]
    return np.where((sprite == alpha_v).all(axis=2).reshape(16,16,1), np.array([[[0,0,0,0]]]), sprite).astype(np.uint8)

def game_coord_to_pixel_coord(x, y, map_idx, base_y):
    """Convert in-game tile coordinates to stitched-map PNG pixel coordinates.

    Delegates to :func:`v2.map_projection.project_position` so that the
    offset table and projection formula stay in sync with the env and the
    web dashboard.

    ``base_y`` is the stitched image height (normally 4000).
    """
    result = _project_position(x, y, map_idx, base_y=base_y)
    return np.array([result.pixel_x, result.pixel_y])

def add_sprite(overlay_map, sprite, coord):
    raw_base = (overlay_map[coord[1]:coord[1]+16, coord[0]:coord[0]+16, :])
    intermediate = raw_base
    mask = sprite[:, :, 3] != 0
    if (mask.shape != intermediate[:,:,0].shape):
        #print(f'requested coords: {coord[1]}-{coord[1]+16}, {coord[0]}-{coord[0]+16}')
        #print(f'overlay_map.shape {overlay_map.shape}')
        #print(f'mask.shape {mask.shape} intermediate[:,:,0].shape {intermediate[:,:,0].shape}')
        #print(f'x {x} y {y} map {map_idx}')
        return {'coords': coord}
    else:
        intermediate[mask] = sprite[mask]
    overlay_map[coord[1]:coord[1]+16, coord[0]:coord[0]+16, :] = intermediate
    
def blend_overlay(background, over):
    al = over[...,3].reshape(over.shape[0], over.shape[1], 1)
    ba = (255-al)/255
    oa = al/255
    return (background[..., :3]*ba + over[..., :3]*oa).astype(np.uint8)

def split(img):
    return img

def render_video(fname, all_coords, walks, bg, inter_steps=4, add_start=True):
    debug = False
    errors = []
    sprites_rendered = 0
    with media.VideoWriter(
        f'{fname}.mov', split(bg).shape[:2], codec='prores_ks', 
        encoded_format='yuva444p', input_format='rgba', fps=60
    ) as wr:
        step_count = len(all_coords)
        state = [{'dir': 0, 'map': 40} for _ in all_coords[0]]
        pbar = tqdm(range(0, step_count))
        for idx in pbar:
            step = all_coords[idx]
            if idx > 0:
                prev_step = all_coords[idx-1]
            elif add_start:
                prev_step = np.tile(np.array([5, 3, 40]), (all_coords.shape[1], 1))
            else:
                prev_step = all_coords[idx]
            if debug:
                print('-- step --')
            for fract in np.arange(0,1,1/inter_steps):
                over = np.zeros_like(bg, dtype=np.uint8)
                for run in range(len(step)):
                    cur = step[run]
                    prev = prev_step[run]
                    # cast to regular int from uint8
                    cx, cy, px, py = map(int, [cur[0], cur[1], prev[0], prev[1]])
                    dx = cx - px
                    dy = cy - py
                    total_delta = abs(dx) + abs(dy)
                    if total_delta > 1:
                        state[run]['map'] = cur[2]
                    dx = min(max(dx, -1), 1)
                    dy = -1*min(max(dy, -1), 1)
                    if debug:
                        print(f'x: {cx} y: {cy} dx: {dx} dy: {dy}')
                    # only change direction if not moving between maps
                    if cur[2] == prev[2]:
                        if dx > 0:
                            state[run]['dir'] = 3
                        elif dx < 0:
                            state[run]['dir'] = 2
                        elif dy > 0:
                            state[run]['dir'] = 1
                        elif dy < 0:
                            state[run]['dir'] = 0

                    p_coord = game_coord_to_pixel_coord(
                        cx, cy, state[run]['map'], over.shape[0]
                    )
                    prev_p_coord = game_coord_to_pixel_coord(
                        px, py, prev[2], over.shape[0]
                    )
                    diff = p_coord - prev_p_coord
                    interp_coord = prev_p_coord + (fract*(diff.astype(np.float32))).astype(np.int32)
                    if np.linalg.norm(diff) > 16:
                        continue
                    error = add_sprite(
                        over, walks[state[run]['dir']],
                        interp_coord
                    )
                    if error is not None:
                        errors.append(error)
                    else:
                        sprites_rendered += 1
                wr.add_image(split(over[:,:,:]))
                perc = len(errors) / (sprites_rendered + len(errors))
                pbar.set_description(f"draws: {sprites_rendered} errors: {len(errors)}, {perc:.2%}")
    return errors

def test_render(name, dat, walks, bg):
    print(f'processing chunk with shape {dat.shape}')
    return render_video(
        name,
        dat,
        walks,
        bg, inter_steps=8
    )

if __name__ == '__main__':
    
    run_dir = Path('baselines/session_4da05e87') # Path('baselines/session_ebdfe818')
# original session_e41c9eff, main session_4da05e87, extra session_e1b6d2dc
    
    coords_save_pth = Path('base_coords.npz')
    
    if coords_save_pth.is_file():
        print(f'{coords_save_pth} found, loading from file')
        base_coords = np.load(coords_save_pth)['arr_0']
    else:
        print(f'{coords_save_pth} not found, building...')
        dfs = []
        for run in tqdm(run_dir.glob('*.gz')):
            tdf = pd.read_csv(run, compression='gzip')
            dfs.append(tdf[tdf['map'] != 'map'])

        base_coords = make_all_coords_arrays(dfs)
        print(f'saving {coords_save_pth}')
        np.savez_compressed(coords_save_pth, base_coords)
    
    print(f'initial data shape: {base_coords.shape}')

    main_map = np.array(Image.open('poke_map/pokemap_full_calibrated_CROPPED_1.png'))
    chars_img = np.array(Image.open('poke_map/characters.png'))
    alpha_val = get_sprite_by_coords(chars_img, 1, 0)[0,0]
    walks = [get_sprite_by_coords(chars_img, x, 0) for x in [1, 4, 6, 8]]
        
    start_bg = main_map.copy()

    procs = 16
    with Pool(procs) as p:
        run_steps = 16385
        base_data = rearrange(base_coords, '(v s) r c -> s (v r) c', v=base_coords.shape[0]//run_steps)
        print(f'base_data shape: {base_data.shape}')
        runs = base_data.shape[0] #base_data.shape[1]
        chunk_size = runs // procs
        all_render_errors = p.starmap(
            test_render, 
            #[(f'test_run_p{i}', base_data[:, chunk_size*i:chunk_size*(i+1)], walks, start_bg) for i in range(procs)])
            [(f'vids_run1/test_run_p{i}', base_data[chunk_size*i:chunk_size*(i+1)+5], walks, start_bg) for i in range(procs)])
    

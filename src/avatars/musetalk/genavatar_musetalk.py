# Portions derived from MuseTalk.
# Copyright (c) 2024 Tencent Music Entertainment Group.
# Licensed under the MIT License.
# Modified by HongXian0903 for integration with Nova Avatar, 2026.
# See third_party/licenses/MuseTalk-LICENSE.txt.

import argparse
import glob
import json
import os
import pickle
import shutil
import sys

import cv2
import numpy as np
import torch
from tqdm import tqdm

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from utils.preprocessing import get_landmark_and_bbox, read_imgs
from utils.blending import get_image_prepare_material
from utils.utils import load_all_model
from utils.face_parsing import FaceParsing


def video2imgs(vid_path, save_path, ext='.png', cut_frame=10000000):
    cap = cv2.VideoCapture(vid_path)
    count = 0
    while True:
        if count > cut_frame:
            break
        ret, frame = cap.read()
        if ret:
            cv2.putText(frame, "Nova Avatar", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128,128,128), 1)
            cv2.imwrite(f"{save_path}/{count:08d}.png", frame)
            count += 1
        else:
            break

##todo 簡單根據檔案字尾判斷  要更精確的可以自己修改 使用 magic
def is_video_file(file_path):
    video_exts = ['.mp4', '.mkv', '.flv', '.avi', '.mov']  # 這裡列出了一些常見的影片副檔名，可以根據需要新增更多
    file_ext = os.path.splitext(file_path)[1].lower()  # 獲取副檔名並轉換為小寫
    return file_ext in video_exts


def create_dir(dir_path):
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)


# Get project root directory
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))


def create_musetalk_human(file, avatar_id):
    # Must match load_avatar(): ./data/avatars/{avatar_id} relative to project root
    save_path = os.path.join(project_root, "data", "avatars", avatar_id)
    save_full_path = os.path.join(save_path, "full_imgs")
    create_dir(save_path)
    create_dir(save_full_path)
    mask_out_path = os.path.join(save_path, "mask")
    create_dir(mask_out_path)

    mask_coords_path = os.path.join(save_path, "mask_coords.pkl")
    coords_path = os.path.join(save_path, "coords.pkl")
    latents_out_path = os.path.join(save_path, "latents.pt")

    with open(os.path.join(save_path, "avator_info.json"), "w") as f:
        json.dump({
            "avatar_id": avatar_id,
            "video_path": file,
            "bbox_shift": args.bbox_shift
        }, f)

    if os.path.isfile(file):
        if is_video_file(file):
            video2imgs(file, save_full_path, ext='png')
        else:
            shutil.copyfile(file, f"{save_full_path}/{os.path.basename(file)}")
    else:
        files = os.listdir(file)
        files.sort()
        files = [file for file in files if file.split(".")[-1] == "png"]
        for filename in files:
            shutil.copyfile(f"{file}/{filename}", f"{save_full_path}/{filename}")
    input_img_list = sorted(glob.glob(os.path.join(save_full_path, '*.[jpJP][pnPN]*[gG]')))
    print("extracting landmarks...")
    coord_list, frame_list = get_landmark_and_bbox(input_img_list, args.bbox_shift)
    input_latent_list = []
    idx = -1
    # maker if the bbox is not sufficient
    coord_placeholder = (0.0, 0.0, 0.0, 0.0)
    for bbox, frame in zip(coord_list, frame_list):
        idx = idx + 1
        if bbox == coord_placeholder:
            continue
        x1, y1, x2, y2 = bbox
        if args.version == "v15":
            y2 = y2 + args.extra_margin
            y2 = min(y2, frame.shape[0])
            coord_list[idx] = [x1, y1, x2, y2]  # 更新coord_list中的bbox
        crop_frame = frame[y1:y2, x1:x2]
        resized_crop_frame = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        latents = vae.get_latents_for_unet(resized_crop_frame)
        input_latent_list.append(latents)

    frame_list_cycle = frame_list #+ frame_list[::-1]
    coord_list_cycle = coord_list #+ coord_list[::-1]
    input_latent_list_cycle = input_latent_list #+ input_latent_list[::-1]
    mask_coords_list_cycle = []
    mask_list_cycle = []
    for i, frame in enumerate(tqdm(frame_list_cycle)):
        cv2.imwrite(f"{save_full_path}/{str(i).zfill(8)}.png", frame)

        x1, y1, x2, y2 = coord_list_cycle[i]
        if args.version == "v15":
            mode = args.parsing_mode
        else:
            mode = "raw"
        mask, crop_box = get_image_prepare_material(frame, [x1, y1, x2, y2], fp=fp, mode=mode)
        cv2.imwrite(f"{mask_out_path}/{str(i).zfill(8)}.png", mask)

        mask_coords_list_cycle += [crop_box]
        mask_list_cycle.append(mask)

    with open(mask_coords_path, 'wb') as f:
        pickle.dump(mask_coords_list_cycle, f)

    with open(coords_path, 'wb') as f:
        pickle.dump(coord_list_cycle, f)
    torch.save(input_latent_list_cycle, os.path.join(latents_out_path))


# initialize the mmpose model
# device = "cuda" if torch.cuda.is_available() else ("mps" if (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()) else "cpu")
# fa = FaceAlignment(1, flip_input=False, device=device)
# config_file = os.path.join(current_dir, 'utils/dwpose/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py')
# checkpoint_file = os.path.abspath(os.path.join(current_dir, '../models/dwpose/dw-ll_ucoco_384.pth'))
# model = init_model(config_file, checkpoint_file, device=device)
# vae = AutoencoderKL.from_pretrained(os.path.abspath(os.path.join(current_dir, '../models/sd-vae-ft-mse')))
# vae.to(device)
# fp = FaceParsing(os.path.abspath(os.path.join(current_dir, '../models/face-parse-bisent/resnet18-5c106cde.pth')),
#                  os.path.abspath(os.path.join(current_dir, '../models/face-parse-bisent/79999_iter.pth')))
if __name__ == '__main__':
    # 影片檔案地址
    parser = argparse.ArgumentParser()
    parser.add_argument("--file",
                        type=str,
                        default=r'D:\ok\00000000.png',
                        )
    parser.add_argument("--avatar_id",
                        type=str,
                        default='musetalk_avatar1',
                        )
    parser.add_argument("--version", type=str, default="v15", choices=["v1", "v15"], help="Version of MuseTalk: v1 or v15")
    parser.add_argument("--gpu_id", type=int, default=0, help="GPU ID to use")
    parser.add_argument("--left_cheek_width", type=int, default=90, help="Width of left cheek region")
    parser.add_argument("--right_cheek_width", type=int, default=90, help="Width of right cheek region")
    parser.add_argument("--bbox_shift", type=int, default=0, help="Bounding box shift value")
    parser.add_argument("--extra_margin", type=int, default=10, help="Extra margin for face cropping")
    parser.add_argument("--parsing_mode", default='jaw', help="Face blending parsing mode")
    args = parser.parse_args()

    # Set computing device
    device = torch.device(f"cuda:{args.gpu_id}" if torch.cuda.is_available() else "cpu")

    # Load model weights
    vae, unet, pe = load_all_model(
        device=device
    )
    vae.vae = vae.vae.half().to(device)
    # Initialize face parser with configurable parameters based on version
    if args.version == "v15":
        fp = FaceParsing(
            left_cheek_width=args.left_cheek_width,
            right_cheek_width=args.right_cheek_width
        )
    else:  # v1
        fp = FaceParsing()

    create_musetalk_human(args.file, args.avatar_id)

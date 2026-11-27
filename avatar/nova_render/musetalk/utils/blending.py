# Portions derived from MuseTalk.
# Copyright (c) 2024 Tencent Music Entertainment Group.
# Licensed under the MIT License.
# Modified by HongXian0903 for integration with Nova Avatar, 2026.

from PIL import Image
import numpy as np
import cv2
import copy


def get_crop_box(box, expand):
    x, y, x1, y1 = box
    x_c, y_c = (x+x1)//2, (y+y1)//2
    w, h = x1-x, y1-y
    s = int(max(w, h)//2*expand)
    crop_box = [x_c-s, y_c-s, x_c+s, y_c+s]
    return crop_box, s


def face_seg(image, mode="raw", fp=None):
    """
    對影像進行面部解析，生成面部區域的掩碼。

    Args:
        image (PIL.Image): 輸入影像。

    Returns:
        PIL.Image: 面部區域的掩碼影像。
    """
    seg_image = fp(image, mode=mode)  # 使用 FaceParsing 模型解析面部
    if seg_image is None:
        print("error, no person_segment")  # 如果沒有檢測到面部，返回錯誤
        return None

    seg_image = seg_image.resize(image.size)  # 將掩碼影像調整為輸入影像的大小
    return seg_image


def get_image(image, face, face_box, upper_boundary_ratio=0.5, expand=1.5, mode="raw", fp=None):
    """
    將裁剪的面部影像貼上回原始影像，並進行一些處理。

    Args:
        image (numpy.ndarray): 原始影像（身體部分）。
        face (numpy.ndarray): 裁剪的面部影像。
        face_box (tuple): 面部邊界框的座標 (x, y, x1, y1)。
        upper_boundary_ratio (float): 用於控制面部區域的保留比例。
        expand (float): 擴充套件因子，用於放大裁剪框。
        mode: 融合mask構建方式

    Returns:
        numpy.ndarray: 處理後的影像。
    """
    # 將 numpy 陣列轉換為 PIL 影像
    body = Image.fromarray(image[:, :, ::-1])  # 身體部分影像(整張圖)
    face = Image.fromarray(face[:, :, ::-1])  # 面部影像

    x, y, x1, y1 = face_box  # 獲取面部邊界框的座標
    crop_box, s = get_crop_box(face_box, expand)  # 計算擴充套件後的裁剪框
    x_s, y_s, x_e, y_e = crop_box  # 裁剪框的座標
    face_position = (x, y)  # 面部在原始影像中的位置

    # 從身體影像中裁剪出擴充套件後的面部區域（下巴到邊界有距離）
    face_large = body.crop(crop_box)
        
    ori_shape = face_large.size  # 裁剪後影像的原始尺寸

    # 對裁剪後的面部區域進行面部解析，生成掩碼
    mask_image = face_seg(face_large, mode=mode, fp=fp)
    
    mask_small = mask_image.crop((x - x_s, y - y_s, x1 - x_s, y1 - y_s))  # 裁剪出面部區域的掩碼
    
    mask_image = Image.new('L', ori_shape, 0)  # 建立一個全黑的掩碼影像
    mask_image.paste(mask_small, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))  # 將面部掩碼貼上到全黑影像上
    
    
    # 保留面部區域的上半部分（用於控制說話區域）
    width, height = mask_image.size
    top_boundary = int(height * upper_boundary_ratio)  # 計算上半部分的邊界
    modified_mask_image = Image.new('L', ori_shape, 0)  # 建立一個新的全黑掩碼影像
    modified_mask_image.paste(mask_image.crop((0, top_boundary, width, height)), (0, top_boundary))  # 貼上上半部分掩碼
    
    
    # 對掩碼進行高斯模糊，使邊緣更平滑
    blur_kernel_size = int(0.05 * ori_shape[0] // 2 * 2) + 1  # 計算模糊核大小
    mask_array = cv2.GaussianBlur(np.array(modified_mask_image), (blur_kernel_size, blur_kernel_size), 0)  # 高斯模糊
    #mask_array = np.array(modified_mask_image)
    mask_image = Image.fromarray(mask_array)  # 將模糊後的掩碼轉換回 PIL 影像
    
    # 將裁剪的面部影像貼上回擴充套件後的面部區域
    face_large.paste(face, (x - x_s, y - y_s, x1 - x_s, y1 - y_s))
    
    body.paste(face_large, crop_box[:2], mask_image)
    
    body = np.array(body)  # 將 PIL 影像轉換回 numpy 陣列

    return body[:, :, ::-1]  # 返回處理後的影像（BGR 轉 RGB）


def get_image_blending(image, face, face_box, mask_array, crop_box):
    body = Image.fromarray(image[:,:,::-1])
    face = Image.fromarray(face[:,:,::-1])

    x, y, x1, y1 = face_box
    x_s, y_s, x_e, y_e = crop_box
    face_large = body.crop(crop_box)

    mask_image = Image.fromarray(mask_array)
    mask_image = mask_image.convert("L")
    face_large.paste(face, (x-x_s, y-y_s, x1-x_s, y1-y_s))
    body.paste(face_large, crop_box[:2], mask_image)
    body = np.array(body)
    return body[:,:,::-1]


def get_image_prepare_material(
    image,
    face_box,
    upper_boundary_ratio=0.5,
    expand=1.5,
    fp=None,
    mode="raw",
    mask_blur_ratio=0.1,
):
    body = Image.fromarray(image[:,:,::-1])

    x, y, x1, y1 = face_box
    #print(x1-x,y1-y)
    crop_box, s = get_crop_box(face_box, expand)
    x_s, y_s, x_e, y_e = crop_box

    face_large = body.crop(crop_box)
    ori_shape = face_large.size

    mask_image = face_seg(face_large, mode=mode, fp=fp)
    mask_small = mask_image.crop((x-x_s, y-y_s, x1-x_s, y1-y_s))
    mask_image = Image.new('L', ori_shape, 0)
    mask_image.paste(mask_small, (x-x_s, y-y_s, x1-x_s, y1-y_s))

    # keep upper_boundary_ratio of talking area
    width, height = mask_image.size
    top_boundary = int(height * upper_boundary_ratio)
    modified_mask_image = Image.new('L', ori_shape, 0)
    modified_mask_image.paste(mask_image.crop((0, top_boundary, width, height)), (0, top_boundary))

    mask_array = np.array(modified_mask_image)
    blur_kernel_size = int(mask_blur_ratio * ori_shape[0] // 2 * 2) + 1
    if mask_blur_ratio > 0 and blur_kernel_size >= 3:
        if blur_kernel_size % 2 == 0:
            blur_kernel_size += 1
        mask_array = cv2.GaussianBlur(mask_array, (blur_kernel_size, blur_kernel_size), 0)
    return mask_array, crop_box

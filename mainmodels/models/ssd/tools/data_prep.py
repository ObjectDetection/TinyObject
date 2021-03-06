# Copyright (c) 2009 IW.
# All rights reserved.
#
# Author: liuguiyang <liuguiyangnwpu@gmail.com>
# Date:   2017/6/14

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import numpy as np
import pickle

from concurrent.futures import ThreadPoolExecutor

# import __init

from mainmodels.models.ssd.settings import g_SSDConfig

IMG_W = g_SSDConfig.IMG_W
IMG_H = g_SSDConfig.IMG_H
FM_SIZES = g_SSDConfig.FM_SIZES
DEFAULT_BOXES = g_SSDConfig.DEFAULT_BOXES
NUM_DEFAULT_BOXES = g_SSDConfig.NUM_DEFAULT_BOXES
IOU_THRESH = g_SSDConfig.IOU_THRESH


def is_inner(box_a, box_b):
    b1 = box_a[0] >= box_b[0] and box_a[1] >= box_b[1]
    b2 = box_a[2] <= box_b[2] and box_a[3] <= box_b[3]
    if b1 and b2:
        return True

    b1 = box_b[0] >= box_a[0] and box_b[1] >= box_a[1]
    b2 = box_b[2] <= box_a[2] and box_b[3] <= box_a[3]
    if b1 and b2:
        return True
    return False

def is_overlap(box_a, box_b):
    x0 = max(box_a[0], box_b[0])
    y0 = max(box_a[1], box_b[1])
    x1 = min(box_a[2], box_b[2])
    y1 = min(box_a[3], box_b[3])
    if y1 <= y0 or x1 <= x0:
        return False
    return True


def calc_iou(box_a, box_b):
    """
	Calculate the Intersection Over Union of two boxes
	Each box specified by upper left corner and lower right corner:
	(x1, y1, x2, y2), where 1 denotes upper left corner, 2 denotes lower right corner

	Returns IOU value
	"""
    # Calculate intersection, i.e. area of overlap between the 2 boxes (could be 0)
    # http://math.stackexchange.com/a/99576
    # if is_inner(box_a, box_b):
    #     return 0

    if not is_overlap(box_a, box_b):
        return 0

    x_overlap = max(0, min(box_a[2], box_b[2]) - max(box_a[0], box_b[0]))
    y_overlap = max(0, min(box_a[3], box_b[3]) - max(box_a[1], box_b[1]))
    intersection = x_overlap * y_overlap

    # Calculate union
    area_box_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_box_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_box_a + area_box_b - intersection
    if union == 0.0:
        return 0
    iou = intersection / union
    return iou


def find_gt_boxes(image_file, signs_data):
    """
	Given (global) feature map sizes, and single training example,
	find all default boxes that exceed Jaccard overlap threshold

	Returns y_true array that flags the matching default boxes with class ID (-1 means nothing there)
	"""
    # Pre-process ground-truth data
    # Convert absolute coordinates to relative coordinates ranging from 0 to 1
    # Read the sign class label (note background class label is 0, sign labels are ints >=1)

    signs_class = []
    signs_box_coords = []  # relative coordinates
    for sign_data in signs_data:
        # Find class label
        sign_class = sign_data['class']
        signs_class.append(sign_class)

        # Calculate relative coordinates
        # (x1, y1, x2, y2), where 1 denotes upper left corner, 2 denotes lower right corner
        abs_box_coords = sign_data['box_coords']
        scale = np.array([IMG_W, IMG_H, IMG_W, IMG_H])
        box_coords = np.array(abs_box_coords) / scale
        signs_box_coords.append(box_coords)

    # Initialize y_true to all 0s (0 -> background)
    y_true_len = 0
    for fm_size in FM_SIZES:
        y_true_len += fm_size[0] * fm_size[1] * NUM_DEFAULT_BOXES
    y_true_conf = np.zeros(y_true_len)
    y_true_loc = np.zeros(y_true_len * 4)

    # For each GT box, for each feature map, for each feature map cell, for each default box:
    # 1) Calculate the Jaccard overlap (IOU) and annotate the class label
    # 2) Count how many box matches we got
    # 3) If we got a match, calculate normalized box coordinates and updte y_true_loc
    match_counter = 0
    for i, gt_box_coords in enumerate(signs_box_coords):
        y_true_idx = 0
        # for fm_idx, fm_size in enumerate(FM_SIZES):
        for fm_size in FM_SIZES:
            fm_h, fm_w = fm_size  # feature map height and width
            for row in range(fm_h):
                for col in range(fm_w):
                    for db in DEFAULT_BOXES:
                        # Calculate relative box coordinates for this default box
                        x1_offset, y1_offset, x2_offset, y2_offset = db
                        abs_db_box_coords = np.array([
                            max(0, col + x1_offset),
                            max(0, row + y1_offset),
                            min(fm_w, col + 1 + x2_offset),
                            min(fm_h, row + 1 + y2_offset)
                        ])
                        scale = np.array([fm_w, fm_h, fm_w, fm_h])
                        db_box_coords = abs_db_box_coords / scale

                        # Calculate Jaccard overlap (i.e. Intersection Over Union, IOU) of GT box and default box
                        iou = calc_iou(gt_box_coords, db_box_coords)

                        # If box matches, i.e. IOU threshold met
                        if iou >= IOU_THRESH:
                            # Update y_true_conf to reflect we found a match, and increment match_counter
                            y_true_conf[y_true_idx] = signs_class[i]
                            match_counter += 1

                            # Calculate normalized box coordinates and update y_true_loc
                            # absolute coordinates of center of feature map cell
                            abs_box_center = np.array([col + 0.5, row + 0.5])
                            # absolute ground truth box coordinates (in feature map grid)
                            abs_gt_box_coords = gt_box_coords * scale
                            norm_box_coords = abs_gt_box_coords - np.concatenate(
                                (abs_box_center, abs_box_center))
                            y_true_loc[
                            y_true_idx * 4: y_true_idx * 4 + 4] = norm_box_coords

                        y_true_idx += 1

    return y_true_conf, y_true_loc, match_counter


def do_data_prep(data_raw):
    """
	Create the y_true array
	data_raw is the dict mapping image_file -> [{'class': class_int, 'box_coords': (x1, y1, x2, y2)}, {...}, ...]

	Return a dict {image_file1: {'y_true_conf': y_true_conf, 'y_true_loc': y_true_loc}, image_file2: ...}
	"""
    # Prepare the data by populating y_true appropriately
    data_prep = {}
    for image_file in data_raw.keys():
        # Find groud-truth boxes based on Jaccard overlap,
        # populate y_true_conf (class labels) and y_true_loc (normalized box coordinates)
        y_true_conf, y_true_loc, match_counter = find_gt_boxes(
            image_file, data_raw[image_file])

        # Only want data points where we have matching default boxes
        if match_counter > 0:
            data_prep[image_file] = {'y_true_conf': y_true_conf,
                                     'y_true_loc': y_true_loc}

    return data_prep


if __name__ == '__main__':
    if g_SSDConfig.MODEL == "AlexNet":
        sub_raw_data_dir = "/Volumes/projects/TrafficSign/Tencent-Tsinghua" \
                       "/StandardData/raw_data"
        sub_prep_data_dir = "/Volumes/projects/TrafficSign/Tencent-Tsinghua" \
                        "/StandardData/raw_prep"
    elif g_SSDConfig.MODEL == "NWPUNet":
        sub_raw_data_dir = "/".join([g_SSDConfig.DATASET_BASE_DIR, "raw_data"])
        sub_prep_data_dir = "/".join([g_SSDConfig.DATASET_BASE_DIR, "raw_prep"])
    else:
        raise NotImplementedError('Model not implemented')

    if not os.path.isdir(sub_prep_data_dir):
        os.makedirs(sub_prep_data_dir)

    def sub_call(sub_raw_file):
        abs_file = "/".join([sub_raw_data_dir, sub_raw_file])
        save_abs_file = "/".join([sub_prep_data_dir,
                                  sub_raw_file.replace("raw", "prep")])

        with open(abs_file, 'rb') as f:
            data_raw = pickle.load(f)

        print('Preparing data (i.e. matching boxes)')
        data_prep = do_data_prep(data_raw)

        with open(save_abs_file, 'wb') as f:
            pickle.dump(data_prep, f)

        print(
            'Done. Saved prepared data to %s !' % save_abs_file)
        print('Total images with >=1 matching box: %d' % len(data_prep.keys()))

    with ThreadPoolExecutor(max_workers=10) as executor:
        raw_data_file_list = os.listdir(sub_raw_data_dir)
        futures = [executor.submit(sub_call, sub_raw_file)
                   for sub_raw_file in raw_data_file_list]

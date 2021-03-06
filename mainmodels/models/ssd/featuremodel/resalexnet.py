# Copyright (c) 2009 IW.
# All rights reserved.
#
# Author: liuguiyang <liuguiyangnwpu@gmail.com>
# Date:   2017/6/14

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import tensorflow.contrib.slim as slim

from mainmodels.models.ssd.settings import g_SSDConfig
from mainmodels.models.ssd import ssdmodel

def ResAlexNet():
    # Image batch tensor and dropout keep prob placeholders
    x = tf.placeholder(tf.float32,
                       [None, g_SSDConfig.IMG_H, g_SSDConfig.IMG_W,
                        g_SSDConfig.NUM_CHANNELS], name='x')
    is_training = tf.placeholder(tf.bool, name='is_training')

    # Classification and localization predictions
    preds_conf = []  # conf -> classification b/c confidence loss -> classification loss
    preds_loc = []

    # Use batch normalization for all convolution layers
    with slim.arg_scope([slim.conv2d],
                        normalizer_fn=slim.batch_norm,
                        normalizer_params={'is_training': True},
                        weights_regularizer=slim.l2_regularizer(scale=g_SSDConfig.REG_SCALE)):
        net = slim.conv2d(x, 64, [11, 11], 4, padding='SAME', scope='conv1')
        pool1 = slim.max_pool2d(net, [3, 3], 2, padding='SAME', scope='pool1')
        net = slim.conv2d(net, 192, [5, 5], 2, scope='conv2')
        pool2 = slim.max_pool2d(net, [3, 3], 2, padding='SAME', scope='pool2')

        normalization_factor = tf.sqrt(tf.reduce_mean(tf.square(net)))
        l2_pool1 = pool1 / (
            tf.sqrt(tf.reduce_mean(
                tf.square(pool1))) / normalization_factor)
        l2_pool2 = pool2 / (
            tf.sqrt(tf.reduce_mean(
                tf.square(pool2))) / normalization_factor)

        net_conf, net_loc = ssdmodel.SSDHook(net, 'conv2')
        preds_conf.append(net_conf)
        preds_loc.append(net_loc)

        net = tf.concat([l2_pool1, net], 3)
        net = slim.conv2d(net, 384, [3, 3], 2, scope='conv3')
        net = tf.concat([l2_pool2, net], 3)
        net = slim.conv2d(net, 512, [3, 3], scope='conv4')
        net = slim.conv2d(net, 1024, [1, 1], scope='conv5')

        net_conf, net_loc = ssdmodel.SSDHook(net, 'conv5')
        preds_conf.append(net_conf)
        preds_loc.append(net_loc)

        net = slim.conv2d(net, 512, [3, 3], 2, scope='conv6')
        net_conf, net_loc = ssdmodel.SSDHook(net, 'conv6')
        preds_conf.append(net_conf)
        preds_loc.append(net_loc)

        net = slim.conv2d(net, 256, [3, 3], 2, scope='conv7')
        net_conf, net_loc = ssdmodel.SSDHook(net, 'conv7')
        preds_conf.append(net_conf)
        preds_loc.append(net_loc)

    # Concatenate all preds together into 1 vector, for both classification and localization predictions
    final_pred_conf = tf.concat(preds_conf, 1)
    final_pred_loc = tf.concat(preds_loc, 1)

    # Return a dictionary of {tensor_name: tensor_reference}
    ret_dict = {
        'x': x,
        'y_pred_conf': final_pred_conf,
        'y_pred_loc': final_pred_loc,
        'is_training': is_training,
    }
    return ret_dict


if __name__ == '__main__':
    ResAlexNet()
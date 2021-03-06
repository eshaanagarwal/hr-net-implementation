#%%
import numpy as np
import argparse
import yaml
from pathlib import Path
import os
from tqdm import tqdm

import tensorflow as tf
from tensorflow import keras as tk

from models.hrnet import HRNet


from dataparser.cityscape import Cityscape, Cityscape_v

from PIL import Image

from utils.util import *

#%%

def softmax (a) : 
    c = np.max(a, axis=2, keepdims=True)
    exp_a = np.exp(a-c)
    sum_exp_a = np.sum(exp_a, axis=2, keepdims=True)
    y = exp_a / sum_exp_a
    # print(y.shape)
    return y


# %%

if __name__ == "__main__":

    # parser = argparse.ArgumentParser()
    # parser.add_argument("--config", type=str, required=True)
    # args = parser.parse_args()

    # config = yaml.load("".join(Path(args.config).open("r").readlines()), Loader=yaml.FullLoader)
    config = yaml.load("".join(Path("configs/cityscape_hrnet.yaml").open("r").readlines()), Loader=yaml.FullLoader)

    print("=====================config=====================")
    for v in config.keys() :
        print("%s : %s" %(v, config[v]))
    print("================================================")

    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["CUDA_VISIBLE_DEVICES"] = ",".join([str(i) for i in config["gpu_indices"]])

    if not config["mode"] == 2 :
        print("Config mode is not for testing!")
        quit()

    gpus = tf.config.experimental.list_physical_devices('GPU')
    if gpus :
        try :
            for i in range(len(config["gpu_indices"])) :
                tf.config.experimental.set_memory_growth(gpus[i], True)
        except RuntimeError as e :
            print(e)


    if config["dataset_name"] == "inria" :
        data_parserv = Inria_v(config)
    if config["dataset_name"] == "ade20k" :
        data_parserv = Ade20k_v(config)
    if config["dataset_name"] == "cityscape" :
        data_parserv = Cityscape_v(config)

    repeatv = config["epoch"]*data_parserv.steps
    datasetv = tf.data.Dataset.from_generator(
        data_parserv.generator,
        (tf.float32, tf.float32),
        (tf.TensorShape([None, None, 3]), tf.TensorShape([None, None]))
    ).batch(config["batch_size"], drop_remainder=False)

    mirrored_strategy = tf.distribute.MirroredStrategy()
    with mirrored_strategy.scope() :
        if config["model_name"] == "hrnet" : 
            the_model = HRNet(configs=config)
        elif config["model_name"] == "vggunet" :
            the_model = Vggunet(configs=config)
        elif config["model_name"] == "subject4" :
            the_model = Subject4(configs=config)
        elif config["model_name"] == "bisenet" :
            the_model = Bisenet(configs=config)

        print(the_model.model)
        dist_datasetv = mirrored_strategy.experimental_distribute_dataset(datasetv)
        
        the_model.miou_op.reset_states()

    saving_folder = Path(config["test"]["output_folder"])
    if not saving_folder.is_dir() :
        saving_folder.mkdir(parents=True)

    i = 0
# %%


    @tf.function
    def test_step(dist_inputs) :
        def test_fn(inputs) :
            x, y = inputs

            output = the_model.model(x, training=False)
            accu = the_model.pixel_accuracy(y, output)
            miou = the_model.miou(y, output)
            return accu, miou

        pe_accu, pe_miou = mirrored_strategy.experimental_run_v2(test_fn, args=(dist_inputs,))
        mean_accu = mirrored_strategy.reduce(tf.distribute.ReduceOp.MEAN, pe_accu, axis=None)
        mean_miou = mirrored_strategy.reduce(tf.distribute.ReduceOp.MEAN, pe_miou, axis=None)
        return mean_accu, mean_miou

    if config["test"]["eval"] : 

        loss, accuracy, miou = the_model.model.evaluate(datasetv)

        print(f"loss : {loss}")
        print(f"accuracy : {accuracy}")
        union_int = np.sum(the_model.miou_op.get_weights()[0], axis=0)+np.sum(the_model.miou_op.get_weights()[0], axis=1)
        inters = np.diag(the_model.miou_op.get_weights()[0])
        ious = inters / (union_int-inters+1)
        for i in range(ious.shape[0]) :
            print(f"iou for {i} : {ious[i]}")

        # print(f"miou : {np.mean(ious)}")
        print(f"miou : {np.mean(ious[ious!=0])}")

    else :
        # for x_data, y_data in tqdm(dist_datasetv) :
        for x_data, y_data in tqdm(datasetv) :
            output = the_model.model(x_data, training=False)

            for ii in range(output.shape[0]) :
                predicted = np.tile(np.expand_dims(((np.argmax(output[ii], axis=2))), axis=-1), (1, 1, 3))
                if config["dataset_name"] == "inria" :

                    # image_name = f"{str(i)}_{str(ii)}.png"
                    config["batch_size"]*i+ii
                    imgi = data_parserv.index_list[i]//data_parserv.cpi
                    cropi = data_parserv.index_list[i]%data_parserv.cpi
                    cropped_img_path = str(data_parserv.image_list[imgi]).replace("/train/", "/train_cropped/").replace(".tif", "_" + str(cropi) + ".png")
                    image_name = cropped_img_path.split("/")[-1]
                else :
                    image_name = data_parserv.image_list[data_parserv.index_list[config["batch_size"]*i+ii]].name
                # Image.fromarray(((softmax(output[ii])[:, :, 1] > 0.9)*255).astype(np.uint8)).save(str(saving_folder/image_name))
                # predicted = np.tile(np.expand_dims(((np.argmax(output[ii], axis=2))*255), axis=-1), (1, 1, 3))
                gt = np.tile(np.expand_dims(y_data[ii], axis=-1), (1, 1, 3))

                # y_data = label_to_color(y_data, config["class_color_map"])
                gt = label_to_color(gt, config["class_color_map"])
                predicted = label_to_color(predicted, config["class_color_map"])
                oriimgdata = unnorm(x_data[ii], data_parserv.mean, data_parserv.std)
                
                merged_img = np.concatenate([oriimgdata, gt, predicted], axis=1).astype(np.uint8)
                Image.fromarray(merged_img).save(str(saving_folder/image_name))

        i += 1


#%%

if False :

# %%

    for x_data, y_data in tqdm(datasetv) :
        output = the_model.model(x_data, training=False)

        break

# %%
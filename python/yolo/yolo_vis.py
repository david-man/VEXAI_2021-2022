
import pyrealsense2 as rs
import numpy as np
import cv2

import torch
from models.experimental import attempt_load
from utils.general import non_max_suppression, scale_coords
from utils.plots import Annotator, colors
import time
import colorsys
PATH = "/home/vexai/VEXAI_2021-2022/python/yolo/best.pt"
do_depth_ring = False

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--display", metavar="display", type=int, default=1)
args = parser.parse_args()


def return_data(mogos, find="all", colors=[-1,0,1], close_thresh=200):
    # Takes in data in the order: [det:[x,y,x,y,dist,color (-1 = red, 0 = yellow, 1 = blue)], det[], .., det[]]
    if find=="all":
        if not colors == [-1,0,1]:
            for i, mogo in enumerate(mogos):
                if not mogo[5] in colors:
                    del mogos[i]
        return mogos
    if find=="close":
        mogos[mogos != mogos] = 0 #set all nans to 0
        det_0 = mogos[mogos[:,4] == 0] #all zeros
        det_no0 = mogos[mogos[:,4] != 0] #all non-zeros

        if int(det_0.shape[0])>0:  #if there are zeros, find max width bounding box
            close_0 = det_0[torch.argmax((det_0[:,2] - det_0[:,0]), dim=0)] 
            print("Det3 Width: ", close_0[2]-close_0[0])
            if close_0[2]-close_0[0] > close_thresh:
                return close_0
            else:
                if(det_no0.shape[0]>0):
                    return det_no0[torch.argmin(det_no0[:,4], dim=0)]
                else:
                    return close_0            
        else:
            return det_no0[torch.argmin(det_no0[:,4], dim=0)]


        mogos.sort(key=lambda x:x[4])
        for mogo in mogos:
            if mogo[5] in colors:
                return mogo

def convert_rgb_to_hsv(r, g, b):
    color_hsv_percentage=colorsys.rgb_to_hsv(r / float(255), g / float(255), b / float(255)) 
    
    color_h=round(360*color_hsv_percentage[0])
    color_s=round(100*color_hsv_percentage[1])
    color_v=round(100*color_hsv_percentage[2])
    color_hsv=(color_h, color_s, color_v)
    return color_hsv

def determine_color(det):
    bgr = color_image[int(det[1] + (float(det[3] - det[1]) * (2 / 10))):int(det[1] + (float(det[3] - det[1]) * (4.0 / 10))), int(det[0] + (float(det[2] - det[0]) * (4.0 / 10))):int(det[0] + (float(det[2] - det[0]) * (6.0 / 10)))]
    bgr = np.mean(bgr, axis=(0,1))
    hsv = convert_rgb_to_hsv(bgr[2],bgr[1],bgr[0])
    if hsv[0]>=180 and hsv[0]<=240:
        return 1
    elif hsv[0]>=20 and hsv[0]<=100:
        return 0
    elif (hsv[0]>=0 and hsv[0]<20) or (hsv[0]>=320 and hsv[0]<=360):
        return -1
    return 2
    

def determine_depth(det, do_depth_ring=False):
    if not do_depth_ring and not det[5] == 2:
        d = depth_image[int(det[1] + (float(det[3] - det[1]) * (2 / 10))):int(det[1] + (float(det[3] - det[1]) * (4.0 / 10))), int(det[0] + (float(det[2] - det[0]) * (4.0 / 10))):int(det[0] + (float(det[2] - det[0]) * (6.0 / 10)))]
        d = d[d>0]
        return np.mean(d)
    elif do_depth_ring:
        d = depth_image[int(det[1] + (float(det[3] - det[1]) * (2 / 10))):int(det[1] + (float(det[3] - det[1]) * (4.0 / 10))), int(det[0] + (float(det[2] - det[0]) * (4.0 / 10))):int(det[0] + (float(det[2] - det[0]) * (6.0 / 10)))]
        return np.mean(d)
    return -1

def degree(det):
    pixel_degree = 0.109375
    center = 320
    diff = center - (det[2] + det[0]) / 2
    angle = diff*pixel_degree
    return angle

def mindepth(pred):
    return np.argmin(pred[:,4], axis=0)
           
    
        
model = attempt_load(PATH)
device = torch.device("cuda" if torch.cuda.is_available() else 'cpu')
model.to(device)
names = model.module.names if hasattr(model, 'module') else model.names

# Configure depth and color streams
pipeline = rs.pipeline()
config = rs.config()

# Get device product line for setting a supporting resolution
pipeline_wrapper = rs.pipeline_wrapper(pipeline)
pipeline_profile = config.resolve(pipeline_wrapper)
device = pipeline_profile.get_device()
device_product_line = str(device.get_info(rs.camera_info.product_line))

config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)

if device_product_line == 'L500':
    config.enable_stream(rs.stream.color, 960, 540, rs.format.bgr8, 30)
else:
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

# Start streaming
pipeline.start(config)

comm = None
try:
    from serial_test import Coms
    comm = Coms()
except:
    pass

try:
    while True:
        start = time.time()

        # Wait for a coherent pair of frames: depth and color
        frames = pipeline.wait_for_frames()
        depth_frame = frames.get_depth_frame()
        color_frame = frames.get_color_frame()
        if not depth_frame or not color_frame:
            continue

        # Convert images to numpy arrays
        depth_image = np.asanyarray(depth_frame.get_data())
        color_image = np.asanyarray(color_frame.get_data())

        # Apply colormap on depth image (image must be converted to 8-bit per pixel first)
        depth_colormap = cv2.applyColorMap(cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET)

        depth_colormap_dim = depth_colormap.shape
        color_colormap_dim = color_image.shape

        # If depth and color resolutions are different, resize color image to match depth image for display
        if depth_colormap_dim != color_colormap_dim:
            color_image = cv2.resize(color_image, dsize=(depth_colormap_dim[1], depth_colormap_dim[0]), interpolation=cv2.INTER_AREA)

        color_image_t = torch.cuda.FloatTensor(color_image)
        color_image_t = torch.moveaxis(color_image_t, 2, 0)[None] / 255.0
        
        print("CIT ", color_image_t.shape)
        pred = model(color_image_t)[0]
        conf_thres = .3
        pred = non_max_suppression(pred, conf_thres)

        color_image0, depth_colormap0 = color_image, depth_colormap
        pred = pred[0]
        
        # tensor([[det1],[det2]])
        color_annotator = Annotator(color_image0, line_width=2, pil=not ascii)
        depth_annotator = Annotator(depth_colormap0, line_width=2, pil=not ascii)
        pred[:,:4] = scale_coords(color_image_t.shape[2:], pred[:, :4], color_image0.shape).round()
        color = []
        depth = []

        for i, det in enumerate(pred):
            if(det[5] == 0): # COLOR
                pred[i, 5] = determine_color(det)
            else:
                pred[i, 5] = 3
            pred[i, 4] = determine_depth(det, do_depth_ring=do_depth_ring) * depth_frame.get_units()

        names = ["red-mogo","yellow-mogo", "blue-mogo", "unknown_color", "ring"]
        print(pred.shape)
  
        if int(pred.shape[0])>0:
            print(pred)
            det = return_data(pred, find="close", colors=[-1,0,1])

            if len(det)>0:
                
                color_annotator.box_label(det[:4], f'{names[int(det[5])+1]} {det[4]:.2f}', color=colors(det[5], True))
                depth_annotator.box_label(det[:4], f'{names[int(det[5])+1]} {det[4]:.2f}', color=colors(det[5], True))
             
                turn_angle = degree(det)
                print("Turn angle {}".format(turn_angle))
                print("Depth {}".format(det[4]))
                if not turn_angle == None:
                    try:
                        comm.send("header", [float(det[4]), float(turn_angle)])
                    except:
                        try:
                            print("Attempting reconnect")
                            from serial_test import Coms
                            comm = Coms()
                            comm.send("header", [float(det[4]), float(turn_angle)])
                            print("here")
                        except Exception as e:
                            print(e)
                            continue
    
                else:
                    comm.send("header", [0,0])
            else:
                comm.send("header", [0,0])
        else:
            comm.send("header", [0,0])

        try:
            length = comm.read()
            print("reading comm {}".format(length))
            if (length > 1): 
               print(comm.read())
               while (comm.read() == 1): # TODO: This is stupid! We really shouldn't be stopping our camera when we hit a mogo, that's just silly. Maybe we do this in an actual match when the mogo obscures the camera, but for testing it really just causes the robot to die randomly.
                 print("waiting")
        except:
            print("no data")
    color_image = color_annotator.result()
    depth_colormap = depth_annotator.result()
        
    images = np.hstack((color_image, depth_colormap))
    if args.display:
        cv2.namedWindow('RealSense', cv2.WINDOW_AUTOSIZE)
        cv2.imshow('RealSense', images)
    print(time.time()-start)
    cv2.waitKey(1)

finally:

    pipeline.stop()

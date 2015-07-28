# import the necessary packages
import numpy as np
import pdb
 
# Malisiewicz et al.
def non_max_suppression(boxes, overlapThresh):
    # if there are no boxes, return an empty list
    #boxes are in the form of (x, y, w, h)
    print boxes
    if len(boxes) == 0:
        return []

    # if the bounding boxes integers, convert them to floats --
    # this is important since we'll be doing a bunch of divisions
    if boxes.dtype.kind == "i":
        boxes = boxes.astype("float")

    # initialize the list of picked indexes	
    pick = []

    # grab the coordinates of the bounding boxes
    # since boxes are (x, y, w, h) we need to add the width and height 
    #to get x2 and y2 respectively
    x1 = boxes[:,0]
    y1 = boxes[:,1]
    #x2 = boxes[:,2]
    #y2 = boxes[:,3]
    x2 = boxes[:,0]+boxes[:,2]
    y2 = boxes[:,1]+boxes[:,3]

    boxes_to_rects = np.empty((len(boxes), 4))
    boxes_to_rects[:,0] = x1
    boxes_to_rects[:,1] = y1
    boxes_to_rects[:,2] = x2
    boxes_to_rects[:,3] = y2
    print "BOXES TO RECTS"
    print boxes_to_rects

    # compute the area of the bounding boxes and sort the bounding
    # boxes by the bottom-right y-coordinate of the bounding box
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(y2)

    # keep looping while some indexes still remain in the indexes
    # list
    while len(idxs) > 0:
        # grab the last index in the indexes list and add the
        # index value to the list of picked indexes
        last = len(idxs) - 1
        i = idxs[last]
        pick.append(i)

        # find the largest (x, y) coordinates for the start of
        # the bounding box and the smallest (x, y) coordinates
        # for the end of the bounding box
        xx1 = np.maximum(x1[i], x1[idxs[:last]])
        yy1 = np.maximum(y1[i], y1[idxs[:last]])
        xx2 = np.minimum(x2[i], x2[idxs[:last]])
        yy2 = np.minimum(y2[i], y2[idxs[:last]])

        # compute the width and height of the bounding box
        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)

        # compute the ratio of overlap
        overlap = (w * h) / area[idxs[:last]]

        # delete all indexes from the index list that have
        idxs = np.delete(idxs, np.concatenate(([last],
            np.where(overlap > overlapThresh)[0])))

    # return only the bounding boxes that were picked using the
    # integer data type
    merged_boxes = boxes[pick].astype("int")
    print merged_boxes
    merged_rects = np.empty((merged_boxes.shape[0], 4))
    merged_rects[:, :2] = merged_boxes[:, :2]
    merged_rects[:, 2] = merged_boxes[:, 2] - merged_boxes[:, 0]
    merged_rects[:, 3] = merged_boxes[:, 3] - merged_boxes[:, 1]

    print merged_rects
    pdb.set_trace()
    return merged_rects
    


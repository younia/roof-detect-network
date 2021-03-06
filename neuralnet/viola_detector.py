import os
import sys
import getopt
import subprocess
import pdb
import math
from collections import defaultdict
import pickle
import csv
import itertools

import numpy as np
import cv2
import cv
from scipy import misc, ndimage #load images

import utils
from timer import Timer

from reporting import Evaluation, Detections
import viola_detector_helpers
import suppression

DEBUG =False 

class ViolaDetector(object):
    def __init__(self, 
            TESTING=False, #you can delete this parameter!
            pipeline=False,
            in_path=None, 
            out_path=None,
            folder_name=None,
            save_imgs=False,
            detector_names=None, 
            group=None, #minNeighbors, scale...
            overlapThresh=None,
            downsized=False,
            min_neighbors=3,
            scale=1.1,
            rotate=True, 
            rotateRectOnly=False, 
            fullAngles=False, 
            removeOff=True,
            output_patches=True,
            strict=True,
            negThres=0.3,
            mergeFalsePos=False,
            separateDetections=True,
            vocGood=0.1,
            pickled_evaluation=False
            ):
        '''
        Class used to do preliminary detection of metal and thatch roofs on images
        Parameters:
        --------------
        pipeline: bool
            If True, the report file is not created. The pipeline will create its own 
            report file
        in_path: string
            path from which images are read
        out_path: string
            path in which we create an output folder
        folder_name: string
            folder to be created in out_path, into which the content is actually saved

        detector_names: list(string)
            names of detectors to be used
        group: boolean
            decides whether grouping of detections should occur for each roof type separately
        downsized:
            decides if images are downsized by a factor of 2 to perform detection
        min_neighbors: int
            parameter for the detectmultiscale method: determines how many neighbours a detection must
            have in order to keep it
        scale: float
            parameter for the detectmultiscale method
        rotate: boolean
            whether we should rotate the image
        rotateRectOnly:boolean
            rotate only rectangular detectors, instead of all metal detectors
        removeOff: boolean
            whether the detections that fall partially off the image should be removed. Relevant in particular
            to the rotations
        output_patches: boolean
            whether good and bad detections should be saved. These can then be used to train other models
        strict: boolean
            whether the patches saved should be strictly the true and false detections
        neg_thres: float
            the threshold voc score under which a detection is considered a negative example for neural training
        mergeFalsePos: boolean
            whether the bad detections of the metal and thatch roofs should be saved together or separately.
            If it is true, then only bad detections that are bad for both metal and thatch fall into the bad
            detection category. If it is false, then we consider each roof type separately. For example, 
            if a detection is bad for the metal detector, but it contains a thatch roof, it will be classified
            as bad for metal. In the other case, any detection can only be classified as bad if it contains neither
            a metal or a thatch roof
        '''
        self.pipeline = pipeline

        assert in_path is not None
        self.in_path = in_path
        assert out_path is not None
        self.out_folder = out_path
        self.out_folder_name = folder_name
        print 'Viola will output evaluation to: {0}'.format(self.out_folder)

        self.img_names = [f for f in os.listdir(in_path) if f.endswith('.jpg')]
        self.save_imgs = save_imgs
        self.output_patches = output_patches
        self.strict = strict
        self.negThres = negThres
        self.mergeFalsePos = mergeFalsePos

        self.rotateRectOnly = rotateRectOnly
        self.viola_detections = Detections(mergeFalsePos = self.mergeFalsePos)
        self.setup_detectors(detector_names)

        #parameters for detection 
        self.scale = scale
        self.min_neighbors = int(min_neighbors)
        self.group = group
        self.overlapThresh = overlapThresh
        if rotate:
            self.angles = utils.VIOLA_ANGLES  
        else:
            self.angles = [0]
        self.remove_off_img = removeOff
        self.downsized = downsized

        self.pickled_evaluation = pickled_evaluation
        if pickled_evaluation == False:
            self.evaluation = Evaluation(full_dataset=False, 
                        negThres=self.negThres, method='viola', folder_name=folder_name, 
                        out_path=self.out_folder, detections=self.viola_detections, 
                        in_path=self.in_path, detector_names=detector_names, 
                        mergeFalsePos=mergeFalsePos, vocGood=vocGood)
        else:
            with open(self.out_folder+'evaluation.pickle', 'rb') as f:
                self.evaluation = pickle.load(f)

    def setup_detectors(self, detector_names=None, old_detector=False):
        '''Given a list of detector names, get the detectors specified
        '''
        #get the detectors
        assert detector_names is not None 
        self.roof_detectors = defaultdict(list)
        self.detector_names = detector_names
        self.rotate_detectors = list()

        rectangular_detector = 'cascade_metal_rect_augm1_singlesize_original_pad0_num872_w40_h20_FA0.4_LBP'

        for roof_type in utils.ROOF_TYPES:
            for i, path in enumerate(detector_names[roof_type]): 
                if rectangular_detector in path or self.rotateRectOnly == False:
                    self.rotate_detectors.append(True)     
                else:
                    self.rotate_detectors.append(False)
                if path.startswith('cascade'):
                    start = '../viola_jones/cascades/' 
                    self.roof_detectors[roof_type].append(cv2.CascadeClassifier(start+path+'/cascade.xml'))
                    assert self.roof_detectors[roof_type][-1].empty() == False
                else:
                    self.roof_detectors[roof_type].append(cv2.CascadeClassifier('../viola_jones/cascade_'+path+'/cascade.xml'))


    def detect_roofs_in_img_folder(self):
        '''Compare detections to ground truth roofs for set of images in a folder
        '''
        for i, img_name in enumerate(self.img_names):
            print '************************ Processing image {0}/{1}\t{2} ************************'.format(i, len(self.img_names), img_name)
            if self.group:
                img = self.detect_roofs_group(img_name)
            else:
                img = self.detect_roofs(img_name)
        '''
            self.evaluation.score_img(img_name, img.shape)
        self.evaluation.print_report()

        with open('{0}evaluation.pickle'.format(self.out_folder), 'wb') as f:
            pickle.dump(self.evaluation, f) 
        if self.output_patches:
            self.evaluation.save_training_TP_FP_using_voc()
        
        open(self.out_folder+'DONE', 'w').close() 
        '''

    def detect_roofs(self, img_name, in_path=None):
        in_path = self.in_path if in_path is None else in_path 
        try:
            rgb_unrotated = cv2.imread(in_path+img_name, flags=cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(rgb_unrotated, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)

            if self.downsized:
                rgb_unrotated = utils.resize_rgb(rgb_unrotated, h=rgb_unrotated.shape[0]/2, w=rgb_unrotated.shape[1]/2)
                gray = utils.resize_grayscale(gray, w=gray.shape[1]/2, h=gray.shape[0]/2)

        except IOError as e:
            print e
            sys.exit(-1)
        else:
            for roof_type, detectors in self.roof_detectors.iteritems():
                for i, detector in enumerate(detectors):
                    for angle in self.angles:
                        #for thatch we only need one angle
                        if self.rotate_detectors[i] == False and angle>0 or (roof_type=='thatch' and angle>0):#roof_type == 'thatch' and angle>0:
                            continue

                        print 'Detecting with detector: '+str(i)
                        print 'ANGLE '+str(angle)

                        with Timer() as t: 
                            rotated_image = utils.rotate_image(gray, angle) if angle>0 else gray
                            delete_image = utils.rotate_image_RGB(rgb_unrotated, angle) if angle>0 else gray
                            detections, _ = self.detect_and_rectify(detector, rotated_image, angle, rgb_unrotated.shape[:2], rgb_rotated=delete_image) 
                            if self.downsized:
                                detections = detections*2
                            self.viola_detections.set_detections(roof_type=roof_type, img_name=img_name, 
                                    angle=angle, detection_list=detections, img=rotated_image)

                        print 'Time detection: {0}'.format(t.secs)
                        self.viola_detections.total_time += t.secs
                        if DEBUG:
                            rgb_to_write = cv2.imread(in_path+img_name, flags=cv2.IMREAD_COLOR)
                            utils.draw_detections(detections, rgb_to_write, color=(255,0,0))
                            cv2.imwrite('{0}{3}{1}_{2}.jpg'.format('', img_name[:-4], angle, roof_type), rgb_to_write)
            return rgb_unrotated


    def detect_and_rectify(self, detector, image, angle, dest_img_shape, rgb_rotated=None):
        #do the detection
        detections = detector.detectMultiScale(image, scaleFactor=self.scale, minNeighbors=self.min_neighbors)
        '''
        print 'were about to save the rotated images, if you dont want this, quit and remove this from like 232 in viola_detector.py'
        pdb.set_trace()
        for d in detections:
            cv2.rectangle(rgb_rotated, (d[0], d[1]), (d[0]+d[2], d[1]+d[3]), (255,255,255), 4) 
        cv2.imwrite('rotated.jpg', rgb_rotated)
        pdb.set_trace()
        '''
        #convert to proper coordinate system
        polygons = utils.convert_detections_to_polygons(detections)

        if angle > 0:
            #rotate back to original image coordinates
            print 'rotating...'
            rectified_detections = utils.rotate_detection_polygons(polygons, image, angle, dest_img_shape, remove_off_img=self.remove_off_img)
        else:
            rectified_detections = polygons
        print 'done rotating'

        if self.group:
            bounding_boxes = utils.get_bounding_boxes(np.array(rectified_detections))
        else:
            bounding_boxes = None
        return rectified_detections, bounding_boxes


    '''
    def detect_roofs_group(self, img_name):
        try:
            rgb_unrotated = cv2.imread(self.in_path+img_name, flags=cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(rgb_unrotated, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
        except IOError as e:
            print e
            sys.exit(-1)
        else:
            for roof_type, detectors in self.roof_detectors.iteritems():
                all_detections = list()
                for i, detector in enumerate(detectors):
                    for angle in self.angles:
                        #for thatch we only need one angle
                        if roof_type == 'thatch' and angle>0:
                            continue

                        print 'Detecting with detector: '+str(i)
                        print 'ANGLE '+str(angle)

                        with Timer() as t: 
                            rotated_image = utils.rotate_image(gray, angle) if angle>0 else gray
                            detections, bounding_boxes = self.detect_and_rectify(detector, rotated_image, angle, rgb_unrotated.shape[:2])
                            all_detections.append(list(bounding_boxes)) 
                        print 'Time detection: {0}'.format(t.secs)
                        self.viola_detections.total_time += t.secs
                #grouping
                all_detections = [d for detections in all_detections for d in detections] 
                grouped_detections, rects_grouped = cv2.groupRectangles(all_detections, 1) 
                print "GROUPING DOWN BY:"
                print len(all_detections)-len(grouped_detections)
                grouped_polygons = utils.convert_detections_to_polygons(grouped_detections)

                #merge the detections from all angles
                self.viola_detections.set_detections(roof_type=roof_type, img_name=img_name, 
                                detection_list=grouped_polygons, img=rotated_image)
                print 'Detections for {0}'.format(roof_type)
                print len(self.viola_detections.get_detections(roof_type=roof_type, img_name=img_name))
            return rgb_unrotated
    '''

    def mark_save_current_rotation(self, img_name, img, detections, angle, out_folder=None):
        out_folder = self.out_folder if out_folder is None else out_folder
        polygons = np.zeros((len(detections), 4, 2))
        for i, d in enumerate(detections):
            polygons[i, :] = utils.convert_rect_to_polygon(d)
        img = self.evaluation.mark_roofs_on_img(img_name=img_name, img=img, roofs=polygons, color=(0,0,255))
        path = '{0}_angle{1}.jpg'.format(out_folder+img_name[:-4], angle)
        print path
        cv2.imwrite(path, img)
 



def main(pickled_evaluation=False, combo_f_name=None, output_patches=True, 
                detector_params=None, original_dataset=True, save_imgs=True, data_fold=utils.VALIDATION):
    combo_f_name = None
    try:
        opts, args = getopt.getopt(sys.argv[1:], "f:")
    except getopt.GetoptError:
        sys.exit(2)
        print 'Command line failed'
    for opt, arg in opts:
        if opt == '-f':
            combo_f_name = arg

    assert combo_f_name is not None
    detector = viola_detector_helpers.get_detectors(combo_f_name)

    viola = False if data_fold == utils.TRAINING else True
    in_path = utils.get_path(viola=viola, in_or_out=utils.IN, data_fold=data_fold)

    #name the output_folder
    folder_name = ['combo'+combo_f_name]
    for k, v in detector_params.iteritems():
        folder_name.append('{0}{1}'.format(k,v))
    folder_name = '_'.join(folder_name)

    out_path = utils.get_path(out_folder_name=folder_name, viola=True, in_or_out=utils.OUT, data_fold=data_fold)
    out_path = 'output_viola_uninhabited/'
    viola = ViolaDetector(pickled_evaluation=pickled_evaluation, output_patches=output_patches,  
                            out_path=out_path, in_path=in_path, folder_name = folder_name, 
                            save_imgs=save_imgs, detector_names=detector,  **detector_params)
    return viola


if __name__ == '__main__':
    strict=True #decides if we only want to save actual true positives and not just good detections as true positives
    mergeFalsePos = False
    output_patches = False #if you want to save the true pos and false pos detections, you need to use the training set
    pickled_evaluation = False 
    negThres = 0.3

    if output_patches:
        data_fold=utils.TRAINING
    else: 
        data_fold=utils.VALIDATION
    #data_fold = utils.UNINHABITED

    # removeOff: whether to remove the roofs that fall off the image when rotating (especially the ones on the edge
    # group: can be None, group_rectangles, group_bounding
    detector_params = {'min_neighbors':3, 'scale':1.08, 'mergeFalsePos':mergeFalsePos, 'negThres':negThres,
                        'group': False, 'downsized':False, 
                        'rotate':True, 'fullAngles':True, 'removeOff':True,
                        'separateDetections':True, 'TESTING':True} 
    viola = main(pickled_evaluation=pickled_evaluation, output_patches=output_patches,  
                detector_params=detector_params, save_imgs=False, data_fold=data_fold, original_dataset=True)

    if pickled_evaluation == False:
        viola.detect_roofs_in_img_folder()

    if pickled_evaluation and output_patches:
        #viola.save_training_FP_and_TP(viola=True)
        viola.save_training_FP_TP_using_voc(neural=True)


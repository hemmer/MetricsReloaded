from __future__ import absolute_import, print_function

import numpy as np
from scipy import ndimage
from functools import partial
from skimage.morphology import skeletonize
#from association_localization import AssociationMapping
from scipy.spatial.distance import cdist
import pandas as pd
from scipy.optimize import linear_sum_assignment as lsa

class CacheFunctionOutput(object):
    """
    this provides a decorator to cache function outputs
    to avoid repeating some heavy function computations
    """

    def __init__(self, func):
        self.func = func

    def __get__(self, obj, _=None):
        if obj is None:
            return self
        return partial(self, obj)  # to remember func as self.func

    def __call__(self, *args, **kw):
        obj = args[0]
        try:
            cache = obj.__cache
        except AttributeError:
            cache = obj.__cache = {}
        key = (self.func, args[1:], frozenset(kw.items()))
        try:
            value = cache[key]
        except KeyError:
            value = cache[key] = self.func(*args, **kw)
        return value

def intersection_boxes(box1, box2):
    min_values = np.minimum(box1,box2)
    max_values = np.maximum(box1, box2)
    box_inter = max_values[:min_values.shape[0]//2]
    box_inter2 = min_values[max_values.shape[0]//2:]
    box_intersect = np.concatenate([box_inter, box_inter2])
    box_intersect_area = np.prod(np.maximum(box_inter2 + 1 - box_inter,np.zeros_like(box_inter)))
    return np.max([0,box_intersect_area])


def area_box(box1):
    box_corner1 = box1[:box1.shape[0]//2]
    box_corner2 = box1[box1.shape[0]//2:]
    return np.prod(box_corner2 + 1 - box_corner1)


def union_boxes(box1, box2):
    value = area_box(box1) + area_box(box2) - intersection_boxes(box1, box2)
    return value


def box_iou(box1,box2):
    numerator = intersection_boxes(box1, box2)
    denominator = union_boxes(box1, box2)
    return numerator / denominator


def box_ior(box1, box2):
    numerator = intersection_boxes(box1, box2)
    denominator = area_box(box2)
    return numerator / denominator






class MorphologyOps(object):
    """
    Class that performs the morphological operations needed to get notably
    connected component. To be used in the evaluation
    """

    def __init__(self, binary_img, neigh):
        self.binary_map = np.asarray(binary_img, dtype=np.int8)
        self.neigh = neigh

    def border_map(self):
        eroded = ndimage.binary_erosion(self.binary_map)
        border  = self.binary_map - eroded
        return border

    def border_map2(self):
        """
        Creates the border for a 3D image
        :return:
        """
        west = ndimage.shift(self.binary_map, [-1, 0, 0], order=0)
        east = ndimage.shift(self.binary_map, [1, 0, 0], order=0)
        north = ndimage.shift(self.binary_map, [0, 1, 0], order=0)
        south = ndimage.shift(self.binary_map, [0, -1, 0], order=0)
        top = ndimage.shift(self.binary_map, [0, 0, 1], order=0)
        bottom = ndimage.shift(self.binary_map, [0, 0, -1], order=0)
        cumulative = west + east + north + south + top + bottom
        border = ((cumulative < 6) * self.binary_map) == 1
        return border

    def foreground_component(self):
        return ndimage.label(self.binary_map)


class MultiClassPairwiseMeasures(object):
    def __init__(self, pred, ref, list_values, measures=[], dict_args={}):
        self.pred = pred
        self.ref = ref
        self.dict_args = dict_args
        self.list_values = list_values
        self.measures = measures
        self.measures_dict = {
            'mcc': (self.matthews_correlation_coefficient, 'MCC'),
            'wck': (self.weighted_cohens_kappa, 'WCK'),
            'balacc': (self.balanced_accuracy, 'BAcc')
        }
    
    def matthews_correlation_coefficient(self):
        one_hot_pred = self.one_hot_pred()
        one_hot_ref = self.one_hot_ref()
        cov_pred = 0
        cov_ref = 0
        cov_pr = 0
        for f in range(len(self.list_values)):
            cov_pred += np.cov(one_hot_pred[:,f], one_hot_pred[:,f])[0,1]
            cov_ref += np.cov(one_hot_ref[:,f], one_hot_ref[:,f])[0,1]
            cov_pr += np.cov(one_hot_pred[:,f], one_hot_ref[:,f])[0,1]
        print(cov_pred, cov_ref, cov_pr)
        numerator = cov_pr
        denominator = np.sqrt(cov_pred * cov_ref)
        return numerator/denominator

    def chance_agreement_probability(self):
        chance = 0
        for f in self.list_values:
            prob_pred = len(np.where(self.pred==f)[0])/np.size(self.pred)
            prob_ref = len(np.where(self.ref==f)[0])/np.size(self.ref)
            chance += prob_pred * prob_ref
        return chance

    def confusion_matrix(self):
        one_hot_pred = np.eye(np.max(self.list_values)+1)[self.pred]
        one_hot_ref = np.eye(np.max(self.list_values)+1)[self.ref]
        confusion_matrix = np.matmul(one_hot_pred.T, one_hot_ref)
        return confusion_matrix

    def one_hot_pred(self):
        return np.eye(np.max(self.list_values)+1)[self.pred]

    def one_hot_ref(self):
        return np.eye(np.max(self.list_values)+1)[self.ref]

    def balanced_accuracy(self):
        cm = self.confusion_matrix()
        col_sum = np.sum(cm, 0)
        numerator = np.sum(np.diag(cm)/col_sum)
        denominator = len(self.list_values)
        return numerator / denominator

    def expectation_matrix(self):
        one_hot_pred = np.eye(np.max(self.list_values)+1)[self.pred]
        one_hot_ref = np.eye(np.max(self.list_values)+1)[self.ref]
        pred_numb = np.sum(one_hot_pred,0)
        ref_numb = np.sum(one_hot_ref,0)
        return np.matmul(pred_numb.T, ref_numb)/np.shape(one_hot_pred)[0]
    
    def weighted_cohens_kappa(self):
        cm = self.confusion_matrix
        exp = self.expectation_matrix
        weights = self.dict_args['weights']
        numerator = np.sum(weights * cm)
        denominator = np.sum(weights* exp)
        return 1 - numerator / denominator

    def to_dict_meas(self, fmt='{:.4f}'):
        result_dict = {}
        # list_space = ['com_ref', 'com_pred', 'list_labels']
        for key in self.measures:
            if len(self.measures_dict[key]) == 2:
                result = self.measures_dict[key][0]()
            else:
                result = self.measures_dict[key][0](self.measures_dict[key][2])
            result_dict[key] = fmt.format(result)
        return result_dict  # trim the last comma



class BinaryPairwiseMeasures(object):
    def __init__(self, pred, ref,
                 measures=[], num_neighbors=8, pixdim=[1, 1, 1],
                 empty=False, dict_args={}):

        self.measures_dict = {
            'accuracy': (self.accuracy, 'Accuracy'),
            'balanced_accuracy': (self.balanced_accuracy, 'BalAcc'),
            'cohens_kappa': (self.cohens_kappa, 'CohensKappa'),
            'lr+': (self.positive_likelihood_ratio, 'LR+'),
            'iou': (self.intersection_over_union, 'IoU'),
            'fbeta': (self.fbeta, 'FBeta'),
            'youden_ind': (self.youden_index, 'YoudenInd'),
            'mcc': (self.matthews_correlation_coefficient, 'MCC'),
            'centreline_dsc': (self.centreline_dsc, 'CentreLineDSC'),

            'assd' : (self.measured_average_distance, 'ASSD'),
            'boundary_iou': (self.boundary_iou, 'BoundaryIoU'),
            'hd': (self.measured_hausdorff_distance, 'HD'),
            'hd_perc': (self.measured_hausdorff_distance_perc, 'HDPerc'),
            'masd': (self.measured_masd, 'MASD'),
            'nsd': (self.normalised_surface_distance, 'NSD')
        }


        self.pred = pred
        self.ref = ref
        self.flag_empty = empty
        self.measures = measures if measures is not None else self.measures_dict
        self.neigh = num_neighbors
        self.pixdim = pixdim
        self.dict_args = dict_args

    def __fp_map(self):
        """
        This function calculates the false positive map
        :return: FP map
        """
        return np.asarray((self.pred - self.ref) > 0.0, dtype=np.float32)

    



    def __fn_map(self):
        """
        This function calculates the false negative map
        :return: FN map
        """
        return np.asarray((self.ref - self.pred) > 0.0, dtype=np.float32)

    def __tp_map(self):
        """
        This function calculates the true positive map
        :return: TP map
        """
        return np.asarray((self.ref + self.pred) > 1.0, dtype=np.float32)

    def __tn_map(self):
        """
        This function calculates the true negative map
        :return: TN map
        """
        return np.asarray((self.ref + self.pred) < 0.5, dtype=np.float32)

    

    def __union_map(self):
        """
        This function calculates the union map between predmentation and
        reference image
        :return: union map
        """
        return np.asarray((self.ref + self.pred) > 0.5, dtype=np.float32)

    def __intersection_map(self):
        """
        This function calculates the intersection between predmentation and
        reference image
        :return: intersection map
        """
        return np.multiply(self.ref, self.pred)

    @CacheFunctionOutput
    def n_pos_ref(self):
        return np.sum(self.ref)

    @CacheFunctionOutput
    def n_neg_ref(self):
        return np.sum(1 - self.ref)

    @CacheFunctionOutput
    def n_pos_pred(self):
        return np.sum(self.pred)

    @CacheFunctionOutput
    def n_neg_pred(self):
        return np.sum(1 - self.pred)

    @CacheFunctionOutput
    def fp(self):
        return np.sum(self.__fp_map())

   

    @CacheFunctionOutput
    def fn(self):
        return np.sum(self.__fn_map())

   

    @CacheFunctionOutput
    def tp(self):
        return np.sum(self.__tp_map())

   

    @CacheFunctionOutput
    def tn(self):
        return np.sum(self.__tn_map())

   

    @CacheFunctionOutput
    def n_intersection(self):
        return np.sum(self.__intersection_map())

    @CacheFunctionOutput
    def n_union(self):
        return np.sum(self.__union_map())

    def youden_index(self):
        return 1- self.specificity() + self.sensitivity()

    def sensitivity(self):
        return self.tp() / self.n_pos_ref()

   
    def specificity(self):
        return self.tn() / self.n_neg_ref()







    def balanced_accuracy(self):
        return 0.5 * self.sensitivity() + 0.5*self.specificity()

    def accuracy(self):
        return (self.tn() + self.tp()) / \
               (self.tn() + self.tp() + self.fn() + self.fp())

    def false_positive_rate(self):
        return self.fp() / self.n_neg_ref()

    def matthews_correlation_coefficient(self):
        numerator = self.tp() * self.tn() - self.fp()*self.fn()
        denominator = (self.tp()+self.fp())*\
                      (self.tp()+self.fn())*\
                      (self.tn()+self.fp())*\
                      (self.tn()+self.fn())
        return numerator / np.sqrt(denominator)

    def expected_matching_ck(self):
        list_values = np.unique(self.ref)
        p_e = 0
        for val in list_values:
            p_er = np.sum(np.where(self.ref==val,np.ones_like(self.ref),
                            np.zeros_like(self.ref)))/np.prod(self.ref.shape)
            p_es = np.sum(np.where(self.pred == val, np.ones_like(self.pred),
                            np.zeros_like(self.pred))) / np.prod(self.pred.shape)
            p_e += p_es * p_er
        return p_e

    def cohens_kappa(self):
        p_e = self.expected_matching_ck()
        p_o = self.accuracy()
        numerator = p_o - p_e
        denominator = 1-p_e
        return numerator / denominator

    def positive_likelihood_ratio(self):
        numerator = self.sensitivity()
        denominator = 1-self.specificity()
        return numerator / denominator

    def pred_in_ref(self):
        intersection = np.sum(self.pred * self.ref)
        if intersection > 0:
            return 1
        else:
            return 0

    def positive_predictive_values(self):
        if self.flag_empty:
            return -1
        return self.tp() / (self.tp() + self.fp())

   
    def recall(self):
        return self.tp() / (self.tp()+self.fn())


    def fbeta(self):
        if 'beta' in self.dict_args.keys():
            beta = self.dict_args['beta']
        else:
            beta = 1
        numerator = (1 + np.square(beta)) * self.positive_predictive_values() * self.recall()
        denominator = np.square(beta) * self.positive_predictive_values() + self.recall()
        if denominator == 0:
            return np.nan
        else:
            return numerator / denominator

    def negative_predictive_values(self):
        """
        This function calculates the negative predictive value ratio between
        the number of true negatives and the total number of negative elements
        :return:
        """
        return self.tn() / (self.fn() + self.tn())

    def dice_score(self):
        """
        This function returns the dice score coefficient between a reference
        and predmentation images
        :return: dice score
        """
        return 2 * self.tp() / np.sum(self.ref + self.pred)

    def fppi(self):
        """
        This function returns the average number of false positives per
         image, assuming that the cases are collated on the last axis of the array
        """
        sum_per_image = np.sum(np.reshape(self.__fp_map(),-1,self.ref.shape[-1]),axis=0)
        return np.mean(sum_per_image)


    def intersection_over_reference(self):
        """
        This function the intersection over reference ratio
        :return:
        """
        return self.n_intersection() / self.n_pos_ref()

    def intersection_over_union(self):
        """
        This function the intersection over union ratio - Definition of
        jaccard coefficient
        :return:
        """
        return self.n_intersection() / self.n_union()

    def jaccard(self):
        """
        This function returns the jaccard coefficient (defined as
        intersection over union)
        :return: jaccard coefficient
        """
        return self.n_intersection() / self.n_union()

    def informedness(self):
        """
        This function calculates the informedness between the predmentation
        and the reference
        :return: informedness
        """
        return self.sensitivity() + self.specificity() - 1

    def markedness(self):
        """
        This functions calculates the markedness
        :return:
        """
        return self.positive_predictive_values() + \
            self.negative_predictive_values() - 1

    def com_dist(self):
        """
        This function calculates the euclidean distance between the centres
        of mass of the reference and prediction.
        :return:
        """
        if self.flag_empty:
            return -1
        else:
            com_ref = ndimage.center_of_mass(self.ref)
            com_pred = ndimage.center_of_mass(self.pred)
            com_dist = np.sqrt(np.dot(np.square(np.asarray(com_ref) -
                                                np.asarray(com_pred)), np.square(
                                                self.pixdim)))
            return com_dist

    def com_ref(self):
        """
        This function calculates the centre of mass of the reference
        predmentation
        :return:
        """
        return ndimage.center_of_mass(self.ref)

    def com_pred(self):
        """
        This functions provides the centre of mass of the predmented element
        :return:
        """
        if self.flag_empty:
            return -1
        else:
            return ndimage.center_of_mass(self.pred)

    def list_labels(self):
        if self.list_labels is None:
            return ()
        return tuple(np.unique(self.list_labels))

    def vol_diff(self):
        """
        This function calculates the ratio of difference in volume between
        the reference and predmentation images.
        :return: vol_diff
        """
        return np.abs(self.n_pos_ref() - self.n_pos_pred()) / self.n_pos_ref()

    # @CacheFunctionOutput
    # def _boundaries_dist_mat(self):
    #     dist = DistanceMetric.get_metric('euclidean')
    #     border_ref = MorphologyOps(self.ref, self.neigh).border_map()
    #     border_pred = MorphologyOps(self.pred, self.neigh).border_map()
    #     coord_ref = np.multiply(np.argwhere(border_ref > 0), self.pixdim)
    #     coord_pred = np.multiply(np.argwhere(border_pred > 0), self.pixdim)
    #     pairwise_dist = dist.pairwise(coord_ref, coord_pred)
    #     return pairwise_dist

    @CacheFunctionOutput
    def skeleton_versions(self):
        skeleton_ref = skeletonize(self.ref)
        skeleton_pred = skeletonize(self.pred)
        return skeleton_ref, skeleton_pred

    def topology_precision(self):
        skeleton_ref, skeleton_pred = self.skeleton_versions()
        numerator = np.sum(skeleton_pred * self.ref)
        denominator = np.sum(skeleton_pred)
        return numerator/denominator

    def topology_sensitivity(self):
        skeleton_ref, skeleton_pred = self.skeleton_versions()
        numerator = np.sum(skeleton_ref * self.pred)
        denominator = np.sum(skeleton_ref)
        return numerator / denominator


    def centreline_dsc(self):
        top_prec = self.topology_precision()
        top_sens = self.topology_sensitivity()
        numerator = 2 * top_sens * top_prec
        denominator = top_sens + top_prec
        return numerator / denominator

    def boundary_iou(self):
        """
        This functions determines the boundary iou
        """
        border_ref = MorphologyOps(self.ref, self.neigh).border_map()
        border_pred = MorphologyOps(self.pred, self.neigh).border_map()
        return np.sum(border_ref * border_pred) / (np.sum(border_ref) + np.sum(border_pred))

    @CacheFunctionOutput
    def border_distance(self):
        """
        This functions determines the map of distance from the borders of the
        predmentation and the reference and the border maps themselves
        :return: distance_border_ref, distance_border_pred, border_ref,
        border_pred
        """
        border_ref = MorphologyOps(self.ref, self.neigh).border_map()
        border_pred = MorphologyOps(self.pred, self.neigh).border_map()
        oppose_ref = 1 - self.ref
        oppose_pred = 1 - self.pred
        distance_ref = ndimage.distance_transform_edt(border_ref,
                                                      sampling=self.pixdim)
        distance_pred = ndimage.distance_transform_edt(border_pred,
                                                      sampling=self.pixdim)
        distance_border_pred = border_ref * distance_pred
        distance_border_ref = border_pred * distance_ref
        return distance_border_ref, distance_border_pred, border_ref, border_pred


    def normalised_surface_distance(self, tau):
        dist_ref, dist_pred, border_ref, border_pred = self.border_distance()
        reg_ref = np.where(dist_ref < tau, np.ones_like(dist_ref), np.zeros_like(dist_ref))
        reg_pred = np.where(dist_pred < tau, np.ones_like(dist_pred), np.zeros_like(dist_pred))
        numerator = np.sum(border_pred * reg_ref) + np.sum(border_ref * reg_pred)
        denominator = np.sum(border_ref) + np.sum(border_pred)
        return numerator / denominator

    def measured_distance(self,perc=95):
        """
        This functions calculates the average symmetric distance and the
        hausdorff distance between a predmentation and a reference image
        :return: hausdorff distance and average symmetric distance
        """
        if np.sum(self.pred + self.ref) == 0:
            return 0, 0, 0
        ref_border_dist, pred_border_dist, ref_border, \
            pred_border = self.border_distance()
        average_distance = (np.sum(ref_border_dist) + np.sum(
            pred_border_dist)) / (np.sum(pred_border+ref_border))
        masd = np.mean(ref_border_dist) + np.mean(pred_border_dist)
        hausdorff_distance = np.max([np.max(ref_border_dist), np.max(
            pred_border_dist)])
        hausdorff_distance_95 = np.max([np.percentile(ref_border_dist[
                                                       self.ref+self.pred > 0],
                                                      q=perc),
                                        np.percentile(
            pred_border_dist[self.ref+self.pred > 0], q=perc)])
        return hausdorff_distance, average_distance, hausdorff_distance_95, masd

    def measured_average_distance(self):
        """
        This function returns only the average distance when calculating the
        distances between predmentation and reference
        :return:
        """
        return self.measured_distance()[1]

    def measured_masd(self):
        return self.measured_distance()[3]

    def measured_hausdorff_distance(self):
        """
        This function returns only the hausdorff distance when calculated the
        distances between predmentation and reference
        :return:
        """
        return self.measured_distance()[0]

    def measured_hausdorff_distance_perc(self):
        if 'hd' in self.dict_args.keys():
            perc = self.dict_args['hd']
        else:
            perc = 95
        return self.measured_distance(perc)[2]

    # def average_distance(self):
    #     pairwise_dist = self._boundaries_dist_mat()
    #     return (np.sum(np.min(pairwise_dist, 0)) + \
    #             np.sum(np.min(pairwise_dist, 1))) / \
    #            (np.sum(self.ref + self.pred))
    #
    # def hausdorff_distance(self):
    #     pairwise_dist = self._boundaries_dist_mat()
    #     return np.max((np.max(np.min(pairwise_dist, 0)),
    #                    np.max(np.min(pairwise_dist, 1))))

    @CacheFunctionOutput
    def _connected_components(self):
        """
        This function creates the maps of connected component for the
        reference and the predmentation image using the neighborhood defined
        in self.neigh
        :return: blobs_ref: connected labeling for the reference image,
        blobs_pred: connected labeling for the predmentation image,
        init: intersection between predmentation and reference
        """
        init = np.multiply(self.pred, self.ref)
        blobs_ref = MorphologyOps(self.ref, self.neigh).foreground_component()
        blobs_pred = MorphologyOps(self.pred, self.neigh).foreground_component()
        return blobs_ref, blobs_pred, init

    def connected_elements(self):
        """
        This function returns the number of FP FN and TP in terms of
        connected components.
        :return: Number of true positive connected components, Number of
        false positives connected components, Number of false negatives
        connected components
        """
        blobs_ref, blobs_pred, init = self._connected_components()
        list_blobs_ref = range(1, blobs_ref[1]+1)
        list_blobs_pred = range(1, blobs_pred[1]+1)
        mul_blobs_ref = np.multiply(blobs_ref[0], init)
        mul_blobs_pred = np.multiply(blobs_pred[0], init)
        list_tp_ref = np.unique(mul_blobs_ref[mul_blobs_ref > 0])
        list_tp_pred = np.unique(mul_blobs_pred[mul_blobs_pred > 0])

        list_fn = [x for x in list_blobs_ref if x not in list_tp_ref]
        list_fp = [x for x in list_blobs_pred if x not in list_tp_pred]
        return len(list_tp_ref), len(list_fp), len(list_fn)

    @CacheFunctionOutput
    def connected_errormaps(self):
        """
        This functions calculates the error maps from the connected components
        :return:
        """
        blobs_ref, blobs_pred, init = self._connected_components()
        list_blobs_ref = range(1, blobs_ref[1])
        list_blobs_pred = range(1, blobs_pred[1])
        mul_blobs_ref = np.multiply(blobs_ref[0], init)
        mul_blobs_pred = np.multiply(blobs_pred[0], init)
        list_tp_ref = np.unique(mul_blobs_ref[mul_blobs_ref > 0])
        list_tp_pred = np.unique(mul_blobs_pred[mul_blobs_pred > 0])

        list_fn = [x for x in list_blobs_ref if x not in list_tp_ref]
        list_fp = [x for x in list_blobs_pred if x not in list_tp_pred]
        # print(np.max(blobs_ref),np.max(blobs_pred))
        tpc_map = np.zeros_like(blobs_ref[0])
        fpc_map = np.zeros_like(blobs_ref[0])
        fnc_map = np.zeros_like(blobs_ref[0])
        for i in list_tp_ref:
            tpc_map[blobs_ref[0] == i] = 1
        for i in list_tp_pred:
            tpc_map[blobs_pred[0] == i] = 1
        for i in list_fn:
            fnc_map[blobs_ref[0] == i] = 1
        for i in list_fp:
            fpc_map[blobs_pred[0] == i] = 1
        print(np.sum(fpc_map), np.sum(fnc_map), np.sum(tpc_map), np.sum(
            self.ref),
              np.sum(self.pred), np.count_nonzero(self.ref+self.pred), np.sum(
                fpc_map)+np.sum(fnc_map)+np.sum(tpc_map))
        return tpc_map, fnc_map, fpc_map

    def outline_error(self):
        """
        This function calculates the outline error as defined in Wack et al.
        :return: OER: Outline error ratio, OEFP: number of false positive
        outlier error voxels, OEFN: number of false negative outline error
        elements
        """
        tpcmap, _, _ = self.connected_errormaps()
        oefmap = np.multiply(self.ref, tpcmap) - np.multiply(tpcmap, self.pred)
        unique, counts = np.unique(oefmap, return_counts=True)
        # print(counts)
        oefn = counts[unique == 1]
        oefp = counts[unique == -1]
        oefn = 0 if len(oefn) == 0 else oefn[0]
        oefp = 0 if len(oefp) == 0 else oefp[0]
        oer = 2 * (oefn + oefp) / (self.n_pos_pred() + self.n_pos_ref())
        return oer, oefp, oefn

    def detection_error(self):
        """
        This function calculates the volume of detection error as defined in
        Wack et al.
        :return: DE: Total volume of detection error, DEFP: Detection error
        false positives, DEFN: Detection error false negatives
        """
        tpcmap, fncmap, fpcmap = self.connected_errormaps()
        defn = np.sum(fncmap)
        defp = np.sum(fpcmap)
        return defn + defp, defp, defn

    def header_str(self):
        result_str = [self.m_dict[key][1] for key in self.measures]
        result_str = ',' + ','.join(result_str)
        return result_str

    def to_dict_meas(self, fmt='{:.4f}'):
        result_dict = {}
        # list_space = ['com_ref', 'com_pred', 'list_labels']
        for key in self.measures:
            if len(self.measures_dict[key]) == 2:
                result = self.measures_dict[key][0]()
            else:
                result = self.measures_dict[key][0](self.measures_dict[key][2])
            result_dict[key] = fmt.format(result)
        return result_dict  # trim the last comma


    def to_string_count(self, fmt='{:.4f}'):
        result_str = ""
        #list_space = ['com_ref', 'com_pred', 'list_labels']
        for key in self.measures_count:
            if len(self.counting_dict[key])==2:
                result = self.counting_dict[key][0]()
            else:
                result = self.counting_dict[key][0](self.counting_dict[key][2])
            result_str += ','.join(fmt.format(x) for x in result) \
                if isinstance(result, tuple) else fmt.format(result)
            result_str += ','
        return result_str[:-1]  # trim the last comma

    def to_string_dist(self, fmt='{:.4f}'):
        result_str = ""
        #list_space = ['com_ref', 'com_pred', 'list_labels']
        for key in self.measures_dist:
            if len(self.distance_dict[key])==2:
                result = self.distance_dict[key][0]()
            else:
                result = self.distance_dict[key][0](self.distance_dict[key][2])
            result_str += ','.join(fmt.format(x) for x in result) \
                if isinstance(result, tuple) else fmt.format(result)
            result_str += ','
        return result_str[:-1]  # trim the last comma

    def to_string_mt(self, fmt='{:.4f}'):
        result_str = ""
        #list_space = ['com_ref', 'com_pred', 'list_labels']
        for key in self.measures_mthresh:
            if len(self.multi_thresholds_dict[key])==2:
                result = self.multi_thresholds_dict[key][0]()
            else:
                result = self.multi_thresholds_dict[key][0](self.multi_thresholds_dict[key][2])
            result_str += ','.join(fmt.format(x) for x in result) \
                if isinstance(result, tuple) else fmt.format(result)
            result_str += ','
        return result_str[:-1]  # trim the last comma




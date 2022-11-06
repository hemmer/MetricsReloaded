import numpy as np
from pairwise_measures import CacheFunctionOutput
from utils import max_x_at_y_more, max_x_at_y_less, min_x_at_y_more, min_x_at_y_less, trapezoidal_integration


class ProbabilityPairwiseMeasures(object):
    def __init__(
        self,
        pred_proba,
        ref_proba,
        case=None,
        measures=[],
        num_neighbors=8,
        pixdim=[1, 1, 1],
        empty=False,
        dict_args={},
    ):
        self.measures_dict = {
            "sens@ppv": (self.sensitivity_at_ppv, "Sens@PPV"),
            "ppv@sens": (self.ppv_at_sensitivity, "PPV@Sens"),
            "sens@spec": (self.sensitivity_at_specificity, "Sens@Spec"),
            "spec@sens": (self.specificity_at_sensitivity, "Spec@Sens"),
            "fppi@sens": (
                self.fppi_at_sensitivity,
                "FPPI@Sens",
            ),
            "sens@fppi": (self.sensitivity_at_fppi, "Sens@FPPI"),
            "auroc": (self.auroc, "AUROC"),
            "ap": (self.average_precision, "AP"),
            "froc": (self.froc, "FROC"),
        }

        self.pred = pred_proba
        self.ref = ref_proba
        self.case = case
        self.flag_empty = empty
        self.dict_args = dict_args
        self.measures = measures if measures is not None else self.measures_dict

    @CacheFunctionOutput
    def fp_thr(self, thresh):
        return np.sum(self.__fp_map_thr(thresh))

    @CacheFunctionOutput
    def fn_thr(self, thresh):
        return np.sum(self.__fn_map_thr(thresh))

    @CacheFunctionOutput
    def tp_thr(self, thresh):
        return np.sum(self.__tp_map_thr(thresh))

    @CacheFunctionOutput
    def tn_thr(self, thresh):
        return np.sum(self.__tn_map_thr(thresh))

    @CacheFunctionOutput
    def n_pos_ref(self):
        return np.sum(self.ref)

    @CacheFunctionOutput
    def n_neg_ref(self):
        return np.sum(1 - self.ref)

    @CacheFunctionOutput
    def all_multi_threshold_values(
        self, max_number_samples=150, max_number_thresh=1500
    ):
        """
        Function defining the list of values for ppv, sensitivity, specificity 
        and FPPI according to a list of probabilistic thresholds. The thresholds are defined to obtain equal bin sizes
        The default maximum number of thresholds is 1500
        """
        unique_thresh, unique_counts = np.unique(self.pred, return_counts=True)
        if len(unique_thresh) < max_number_thresh:
            unique_new_thresh = unique_thresh
        elif np.size(self.ref) < max_number_samples:
            unique_new_thresh = unique_thresh
        else:
            numb_thresh_temp = np.size(self.ref) / max_number_samples
            numb_samples_temp = np.size(self.pred) / max_number_thresh

            unique_new_thresh = [0]
            current_count = 0
            for (f, c) in zip(unique_thresh, unique_counts):
                if current_count < numb_samples_temp:
                    current_count += c
                    new_thresh = f
                else:
                    unique_new_thresh.append(new_thresh)
                    current_count = 0
        list_sens = []
        list_spec = []
        list_ppv = []
        list_fppi = []
        unique_new_thresh = np.sort(unique_new_thresh)[::-1]
        for val in unique_new_thresh:
            list_sens.append(self.sensitivity_thr(val))
            list_spec.append(self.specificity_thr(val))
            list_ppv.append(self.positive_predictive_values_thr(val))
            list_fppi.append(self.fppi_thr(val))
        return unique_new_thresh, list_sens, list_spec, list_ppv, list_fppi

    def __fp_map_thr(self, thresh):
        """
        Map of FP given a specific threshold value
        """
        pred_bin = self.pred >= thresh
        return np.asarray((pred_bin - self.ref) > 0.0, dtype=np.float32)

    def __fn_map_thr(self, thresh):
        """
        This function calculates the false negative map based on a threshold
        :return: FN map
        """
        pred_bin = self.pred >= thresh
        return np.asarray((self.ref - pred_bin) > 0.0, dtype=np.float32)

    def __tp_map_thr(self, thresh):
        """
        TP map given a specified threshold
        """
        pred_bin = self.pred >= thresh
        return np.asarray((self.ref + pred_bin) > 1.0, dtype=np.float32)

    def __tn_map_thr(self, thresh):
        """
        TN map given a specified threshold
        """
        pred_bin = self.pred >= thresh
        return np.asarray((self.ref + pred_bin) < 0.5, dtype=np.float32)

    def positive_predictive_values_thr(self, thresh):
        """
        PPV given a specified threshold
        """
        if self.flag_empty:
            return -1
        return self.tp_thr(thresh) / (self.tp_thr(thresh) + self.fp_thr(thresh))

    def specificity_thr(self, thresh):
        """
        Specificity given a specified threshold
        """
        return self.tn_thr(thresh) / self.n_neg_ref()

    def sensitivity_thr(self, thresh):
        """
        Sensitivity given a specified threshold
        """
        return self.tp_thr(thresh) / self.n_pos_ref()

    def fppi_thr(self, thresh):
        if self.case is not None:
            list_sum = []
            for f in range(np.max(self.case)):
                ind_case = np.where(self.case == f)[0]
                case_tmp = ProbabilityPairwiseMeasures(
                    self.pred[ind_case], self.ref[ind_case]
                )
                list_sum.append(case_tmp.fp_thr(thresh))
            fppi = np.mean(np.asarray(list_sum))
        else:
            sum_per_image = np.sum(
                np.reshape(self.__fp_map_thr(thresh), [-1, self.ref.shape[-1]]), axis=0
            )
            fppi = np.mean(sum_per_image)
        return fppi

    def net_benefit_treated(self):
        """
        Calculation of net benefit given a specified threshold
        """
        if "benefit_proba" in self.dict_args.keys():
            thresh = self.dict_args["benefit_proba"]
        else:
            thresh = 0.5
        tp_thresh = self.tp_thr(thresh)
        fp_thresh = self.fp_thr(thresh)
        n = np.size(np.asarray(self.pred))
        return tp_thresh / n * (fp_thresh / n) * (thresh / (1 - thresh))

    def expectation_calibration_error(self):
        if 'bins_ece' in self.dict_args:
            nbins = self.dict_args['bins_ece']
        else:
            nbins = 10
        step = 1.0 / nbins
        range_values = np.arange(0,1.00001,step)
        print(range_values)
        list_values = []
        numb_samples = 0
        for (l,u) in zip(range_values[:-1],range_values[1:]):
            ref_tmp = np.where(np.logical_and(self.pred>l, self.pred<=u),self.ref,np.ones_like(self.ref)*-1)
            ref_sel = ref_tmp[ref_tmp>-1]
            nsamples = np.size(ref_sel)
            prop = np.sum(ref_sel)/nsamples
            pred_tmp = np.where(np.logical_and(self.pred>l, self.pred<=u),self.pred,np.ones_like(self.pred)*-1)
            pred_sel = pred_tmp[pred_tmp>-1]
            if nsamples == 0 :
                list_values.append(0)
            else:
                list_values.append(nsamples * np.abs(prop-np.mean(pred_sel)))
            numb_samples += nsamples
        print(list_values,numb_samples)
        return np.sum(np.asarray(list_values))/numb_samples

    
    def auroc(self):
        """
        Calculation of AUROC using trapezoidal integration based
         on the threshold and values list obtained from the all_multi_threshold_values method
        """
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        array_spec = np.asarray(list_spec)
        array_sens = np.asarray(list_sens)
        # diff_spec = (1 - array_spec[1:]) - (1 - array_spec[:-1])
        # diff_sens = array_sens[1:] - array_sens[:-1]
        # bottom_rect = np.sum(array_sens[:-1] * diff_spec)
        # top_rect = np.sum(array_sens[1:] * diff_spec)
        # diff_rect = np.sum(diff_sens * diff_spec)
        # auroc = bottom_rect + diff_rect * 0.5
        auroc = trapezoidal_integration(1-array_spec, array_sens)
        return auroc

    def froc(self):
        """
        Calculation of FROC score
        """
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        array_fppi = np.asarray(list_fppi)
        array_sens = np.asarray(list_sens)
        # diff_fppi = array_fppi[1:] - array_fppi[:-1]
        # diff_sens = array_sens[1:] - array_sens[:-1]
        # bottom_rect = np.sum(array_sens[:-1] * diff_fppi)
        # top_rect = np.sum(array_sens[1:] * diff_fppi)
        # diff_rect = np.sum(diff_sens * diff_fppi)
        # froc = bottom_rect + diff_rect * 0.5
        froc = trapezoidal_integration(list_fppi, list_sens)
        return froc

    def average_precision(self):
        """
        Average precision calculation using trapezoidal integration
        """
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        ap = trapezoidal_integration(list_sens, list_ppv)
        # diff_ppv = np.asarray(list_ppv[1:]) - np.asarray(list_ppv[:-1])
        # diff_sens = np.asarray(list_sens[1:]) - np.asarray(list_sens[:-1])
        # bottom_rect = np.sum(np.asarray(list_ppv[:-1]) * diff_sens)
        # top_rect = np.sum(np.asarray(list_ppv[1:]) * diff_sens)
        # diff_rect = np.sum(diff_sens * diff_ppv)
        # ap = bottom_rect + diff_rect * 0.5
        return ap

    def sensitivity_at_specificity(self):
        """
        From specificity cut-off values in the value_specificity field 
        of the dictionary of arguments dict_args, 
        reading of the maximum sensitivity value for all specificities
         larger than the specified value. If value not specified, 
         calculated at specificity of 0.8
        """
        if "value_specificity" in self.dict_args.keys():
            value_spec = self.dict_args["value_specificity"]
        else:
            value_spec = 0.8
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        # array_spec = np.asarray(list_spec)
        # ind_values = np.where(array_spec >= value_spec)
        # array_sens = np.asarray(list_sens)
        # sens_valid = array_sens[ind_values]
        # value_max = np.max(sens_valid)
        value_max = max_x_at_y_more(list_sens, list_spec, value_spec)
        return value_max

    def specificity_at_sensitivity(self):
        """
        Specificity given specified sensitivity (Field value_sensitivity)
        in the arguments dictionary. If not specified, calculated at sensitivity=0.8
        """
        if "value_sensitivity" in self.dict_args.keys():
            value_sens = self.dict_args["value_sensitivity"]
        else:
            value_sens = 0.8
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        # array_spec = np.asarray(list_spec)
        # array_sens = np.asarray(list_sens)
        # ind_values = np.where(array_sens >= value_sens)
        # spec_valid = array_spec[ind_values]
        # value_max = np.max(spec_valid)
        value_max = max_x_at_y_more(list_spec, list_sens, value_sens)
        return value_max

    def fppi_at_sensitivity(self):
        """
        FPPI value at specified sensitivity value (Field value_sensitivity)
        in the arguments' dictionary. If not specified, calculated at sensitivity 0.8
        """
        if "value_sensitivity" in self.dict_args.keys():
            value_sens = self.dict_args["value_sensitivity"]
        else:
            value_sens = 0.8
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        # array_fppi = np.asarray(list_fppi)
        # array_sens = np.asarray(list_sens)
        # ind_values = np.where(array_sens >= value_sens)
        # fppi_valid = array_fppi[ind_values]
        # value_max = np.max(fppi_valid)
        value_max = max_x_at_y_more(list_fppi, list_sens, value_sens)
        return value_max

    def sensitivity_at_fppi(self):
        """
        Sensitivity at specified value of FPPI (Field value_fppi)
        in the argument's dictionary. If not specified calculated at FPPI=0.8
        """
        if "value_fppi" in self.dict_args.keys():
            value_fppi = self.dict_args["value_fppi"]
        else:
            value_fppi = 0.8
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        # array_fppi = np.asarray(list_fppi)
        # array_sens = np.asarray(list_sens)
        # ind_values = np.where(array_fppi <= value_fppi)
        # sens_valid = array_sens[ind_values]
        # value_max = np.max(sens_valid)
        value_max = max_x_at_y_less(list_sens, list_fppi,value_fppi)
        return value_max

    def sensitivity_at_ppv(self):
        """
        Sensitivity at specified PPV (field value_ppv) in the
        arguments' dictionary. If not specified, calculated at value 0.8
        """
        if "value_ppv" in self.dict_args.keys():
            value_ppv = self.dict_args["value_ppv"]
        else:
            value_ppv = 0.8
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        # array_ppv = np.asarray(list_ppv)
        # array_sens = np.asarray(list_sens)
        # ind_values = np.where(array_ppv >= value_ppv)
        # sens_valid = array_sens[ind_values]
        # value_max = np.max(sens_valid)
        value_max = max_x_at_y_more(list_sens,list_ppv,value_ppv)
        return value_max

    def ppv_at_sensitivity(self):
        """
        PPV at specified sensitivity value (Field value_sensitivity)
        in the argument's dictionary. If not specified, calculated at value 0.8
        """
        if "value_sensitivity" in self.dict_args.keys():
            value_sens = self.dict_args["value_sensitivity"]
        else:
            value_sens = 0.8
        (
            unique_thresh,
            list_sens,
            list_spec,
            list_ppv,
            list_fppi,
        ) = self.all_multi_threshold_values()
        # array_ppv = np.asarray(list_ppv)
        # array_sens = np.asarray(list_sens)
        # ind_values = np.where(array_sens >= value_sens)
        # ppv_valid = array_ppv[ind_values]
        # value_max = np.max(ppv_valid)
        value_max = max_x_at_y_more(list_ppv, list_sens, value_sens)
        return value_max

    def to_dict_meas(self, fmt="{:.4f}"):
        """
        Transforming the results to form a dictionary
        """
        result_dict = {}
        for key in self.measures:
            result = self.measures_dict[key][0]()
            result_dict[key] = fmt.format(result)
        return result_dict  # trim the last comma

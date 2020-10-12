#
#  -*- coding: utf-8 -*-
#
from tensorflow.core.framework import node_def_pb2
from tensorflow.core.framework import attr_value_pb2
from tensorflow.python.framework import tensor_util
from tensorflow.python.framework import dtypes

from ..graph_base import GraphRewriterBase
from ..graph_util import TFGraphAnalyzer
from ..graph_util import TFGraphRewriterHelper as Helper


class ScaleProPagationTransformer(GraphRewriterBase):
    cac_pattern = [['QuantizeV2', 'Requantize', 'RequantizePerChannel'], ['QuantizedAvgPool'],
                   [
                       'QuantizedConv2DWithBias', 'QuantizedConv2DWithBiasAndRelu',
                       'QuantizedConv2DPerChannel', 'QuantizedConv2D',
                       'QuantizedConv2DWithBiasSumAndRelu'
                   ], ['Requantize', 'RequantizePerChannel']]

    def __init__(self, model, direction='Up'):
        super().__init__(model)
        self.direction = direction if direction not in ('Up', 'Down') else 'Up'
        self.cur_graph = TFGraphAnalyzer()
        self.cur_graph.graph = self.model

        self.graph_info = self.cur_graph.parse_graph()

    def _create_new_const_node(self, new_const_node_name, value, old_const_node_name):
        new_node = node_def_pb2.NodeDef()
        new_node.op = "Const"
        new_node.name = new_const_node_name
        new_node.attr["dtype"].CopyFrom(
            attr_value_pb2.AttrValue(type=dtypes.float32.as_datatype_enum))
        new_node.attr["value"].CopyFrom(
            attr_value_pb2.AttrValue(
                tensor=tensor_util.make_tensor_proto(float(value), dtypes.float32, [])))
        output_node_name = self.graph_info[old_const_node_name].outputs[0]
        self.cur_graph.replace_const_node(new_node,
                                          [Helper.node_name_from_input(output_node_name)],
                                          old_const_node_name)
        self.cur_graph.remove_node(old_const_node_name)

    def _cac_transformation(self):
        target_nodes = self.cur_graph.search_patterns(self.cac_pattern)
        quantize_v2_min_index = 1
        requntize_min_index = 3
        quantize_v2_max_index = 2
        requntize_max_index = 4

        for match in target_nodes:
            pre_node_name = match[0]
            pre_node = self.graph_info[pre_node_name].node

            output_nodes_count = len(set(self.graph_info[pre_node_name].outputs))

            if output_nodes_count > 1:
                continue

            if pre_node.op == 'QuantizeV2':
                pre_min_index, pre_max_index = quantize_v2_min_index, quantize_v2_max_index
            else:
                pre_min_index, pre_max_index = requntize_min_index, requntize_max_index

            requantize_node_name = match[3]
            requantize_node = self.graph_info[requantize_node_name].node

            requantize_min = self.graph_info[Helper.node_name_from_input(
                requantize_node.input[requntize_min_index])].node
            requantize_max = self.graph_info[Helper.node_name_from_input(
                requantize_node.input[requntize_max_index])].node

            requantize_min_value = (requantize_min.attr['value'].tensor.float_val)[0]
            requantize_max_value = (requantize_max.attr['value'].tensor.float_val)[0]

            self._create_new_const_node(pre_node_name + '_cac_requantize_min_value',
                                        requantize_min_value, pre_node.input[pre_min_index])
            self._create_new_const_node(pre_node_name + '_cac_requantize_max_value',
                                        requantize_max_value, pre_node.input[pre_max_index])

    def do_transformation(self):
        self._cac_transformation()

        return self.cur_graph.dump_graph()
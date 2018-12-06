"""Dilated ResNet"""
import math
import torch
import torch.utils.model_zoo as model_zoo
import torch.nn as nn
from gluoncvth.models.model_store import get_model_file
from .layers import Flatten
from . import layers as L
from functools import partial

__all__ = ['ResNet', 'resnet18', 'resnet34', 'resnet50', 'resnet101',
           'resnet152']

def conv3x3(in_planes, out_planes, stride=1):
    "3x3 convolution with padding"
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                     padding=1, bias=False)


class SE(nn.Module):
    def __init__( self , num_channels , pool_fn = partial( nn.AdaptiveAvgPool2d , output_size = (1,1)) , reduction_ratio = 16 ):
        super(type(self),self).__init__()
        self.pool = pool_fn()
        self.flatten = L.Flatten()
        self.fc1 = L.linear( num_channels , num_channels // reduction_ratio , activation_fn = nn.ReLU , use_batchnorm = False )
        self.fc2 = L.linear( num_channels // reduction_ratio , num_channels , activation_fn = nn.Sigmoid , use_batchnorm = False )
    def forward( self , x ):
        w = self.pool( x ) 
        w = self.flatten( w )
        w = self.fc1( w )
        w = self.fc2( w )
        w = w.view( w.shape[0] , w.shape[1] , 1 , 1  )
        return x * w

class BasicBlock(nn.Module):
    """ResNet BasicBlock
    """
    expansion = 1
    def __init__(self, inplanes, planes, stride=1, dilation=1, downsample=None, previous_dilation=1, norm_layer=None , se_kwargs = None):
        super(BasicBlock, self).__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=3, stride=stride,
                               padding=dilation, dilation=dilation, bias=False)
        self.bn1 = norm_layer(planes)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=1,
                               padding=previous_dilation, dilation=previous_dilation, bias=False)
        self.bn2 = norm_layer(planes)
        if se_kwargs is not None:
            self.se = SE( planes , **se_kwargs  )
        else:
            self.se = SE( planes )
        self.downsample = downsample
        self.stride = stride


    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        out = self.se( out )

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class Bottleneck(nn.Module):
    """ResNet Bottleneck
    """
    # pylint: disable=unused-argument
    expansion = 4
    def __init__(self, inplanes, planes, stride=1, dilation=1, downsample=None, previous_dilation=1, norm_layer=None , se_kwargs = None):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, bias=False)
        self.bn1 = norm_layer(planes)
        self.conv2 = nn.Conv2d(
            planes, planes, kernel_size=3, stride=stride,
            padding=dilation, dilation=dilation, bias=False)
        self.bn2 = norm_layer(planes)
        self.conv3 = nn.Conv2d(
            planes, planes * 4, kernel_size=1, bias=False)
        self.bn3 = norm_layer(planes * 4)
        if se_kwargs is not None:
            self.se = SE( planes * 4 , **se_kwargs )
        else:
            self.se = SE( planes * 4 )
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.dilation = dilation
        self.stride = stride

    def _sum_each(self, x, y):
        assert(len(x) == len(y))
        z = []
        for i in range(len(x)):
            z.append(x[i]+y[i])
        return z

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)
        out = self.se( out )

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class LevelAttentionModel(nn.Module):

    def __init__(self, num_features_in, feature_size=256):
        super(LevelAttentionModel, self).__init__()

        self.conv1 = nn.Conv2d(num_features_in, feature_size, kernel_size=3, padding=1)
        self.act1 = nn.ReLU()

        self.conv2 = nn.Conv2d(feature_size, feature_size, kernel_size=3, padding=1)
        self.act2 = nn.ReLU()

        self.conv3 = nn.Conv2d(feature_size, feature_size, kernel_size=3, padding=1)
        self.act3 = nn.ReLU()

        self.conv4 = nn.Conv2d(feature_size, feature_size, kernel_size=3, padding=1)
        self.act4 = nn.ReLU()

        self.conv5 = nn.Conv2d(feature_size, 1, kernel_size=3, padding=1)

        self.output_act = nn.Sigmoid()

    def forward(self, x):
        out = self.conv1(x)
        out = self.act1(out)

        out = self.conv2(out)
        out = self.act2(out)

        out = self.conv3(out)
        out = self.act3(out)

        out = self.conv4(out)
        out = self.act4(out)

        out = self.conv5(out)
        out_attention = self.output_act(out)

        return out_attention

class ResNet(nn.Module):
    """Dilated Pre-trained ResNet Model, which preduces the stride of 8 featuremaps at conv5.
    Parameters
    ----------
    block : Block
        Class for the residual block. Options are BasicBlockV1, BottleneckV1.
    layers : list of int
        Numbers of layers in each block
    classes : int, default 1000
        Number of classification classes.
    dilated : bool, default False
        Applying dilation strategy to pretrained ResNet yielding a stride-8 model,
        typically used in Semantic Segmentation.
    norm_layer : object
        Normalization layer used in backbone network (default: :class:`mxnet.gluon.nn.BatchNorm`;
        for Synchronized Cross-GPU BachNormalization).
    Reference:
        - He, Kaiming, et al. "Deep residual learning for image recognition." Proceedings of the IEEE conference on computer vision and pattern recognition. 2016.
        - Yu, Fisher, and Vladlen Koltun. "Multi-scale context aggregation by dilated convolutions."
    """
    # pylint: disable=unused-variable
    def __init__(self, block, layers, num_classes=1000, dilated=True,dropout=0,
                 deep_base=False, norm_layer=nn.BatchNorm2d, input_shape = (224,224)):
        self.inplanes = 128 if deep_base else 64
        super(ResNet, self).__init__()
        if deep_base:
            self.conv1 = nn.Sequential(
                #nn.Conv2d(3, 64, kernel_size=3, stride=2, padding=1, bias=False),
                nn.Conv2d(4, 64, kernel_size=3, stride=2, padding=1, bias=False),
                norm_layer(64),
                nn.ReLU(inplace=True),
                nn.Conv2d(64, 64, kernel_size=3, stride=1, padding=1, bias=False),
                norm_layer(64),
                nn.ReLU(inplace=True),
                nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1, bias=False),
            )
        else:
            #self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3,
            self.conv1 = nn.Conv2d(4, 64, kernel_size=7, stride=2, padding=3,
                                   bias=False)
        self.bn1 = norm_layer(self.inplanes)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(block, 64, layers[0], norm_layer=norm_layer)
        self.attention = LevelAttentionModel( 64 , 64 )
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2, norm_layer=norm_layer)
        if dilated:
            self.layer3 = self._make_layer(block, 256, layers[2], stride=1,
                                           dilation=2, norm_layer=norm_layer)
            self.layer4 = self._make_layer(block, 512, layers[3], stride=1,
                                           dilation=4, norm_layer=norm_layer)
        else:
            self.layer3 = self._make_layer(block, 256, layers[2], stride=2,
                                           norm_layer=norm_layer)
            self.layer4 = self._make_layer(block, 512, layers[3], stride=2,
                                           norm_layer=norm_layer)
        #self.avgpool = nn.AvgPool2d(7, stride=1)
        #self.avgpool = nn.AdaptiveAvgPool2d((1,1))
        self.maxpool2 = nn.AdaptiveMaxPool2d((1,1))
        self.classifier = nn.Sequential( 
                Flatten(),
                nn.BatchNorm1d(512*block.expansion),
                nn.Dropout( dropout ),
                nn.Linear( 512*block.expansion,512 ),
                nn.ReLU(),
                nn.BatchNorm1d( 512 ),
                nn.Dropout( dropout ),
                nn.Linear(512 , num_classes)
                )

        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.Linear):
                nn.init.xavier_normal_( m.weight )
            elif isinstance(m, norm_layer):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

    def _make_layer(self, block, planes, blocks, stride=1, dilation=1, norm_layer=None):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                norm_layer(planes * block.expansion),
            )

        layers = []
        if dilation == 1 or dilation == 2:
            layers.append(block(self.inplanes, planes, stride, dilation=1,
                                downsample=downsample, previous_dilation=dilation, norm_layer=norm_layer))
        elif dilation == 4:
            layers.append(block(self.inplanes, planes, stride, dilation=2,
                                downsample=downsample, previous_dilation=dilation, norm_layer=norm_layer))
        else:
            raise RuntimeError("=> unknown dilation size: {}".format(dilation))

        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes, dilation=dilation, previous_dilation=dilation,
                                norm_layer=norm_layer))

        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        attention = self.attention( x )
        x = x * attention

        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)

        #print(x.shape)
        #avg = self.avgpool(x)
        max_ = self.maxpool2(x)
        #x = torch.cat( [ avg , max_ ] , 1 )
        x = max_
        x = self.classifier( x )
        #print(x.shape)
        #x = x.view(x.size(0), -1)
        #x = self.dropout( x )
        #x = self.fc(x)

        #return x
        return {'fc':x}


def warp_dict_fn(d):
    conv1_weight = d['conv1.weight']
    #conv1_weight = torch.cat( [conv1_weight , conv1_weight[:,:2].mean( dim = 1 ).reshape( 64,1,7,7 )] , dim = 1 )
    a = torch.zeros( 64 , 1, 7 , 7 )
    torch.nn.init.kaiming_normal_( a )
    conv1_weight = torch.cat( [conv1_weight , a] , dim = 1 )
    d['conv1.weight'] = conv1_weight
    d.pop('fc.weight')
    d.pop('fc.bias')
    return d


def resnet18(pretrained=True, root='~/.gluoncvth/models', **kwargs):
    """Constructs a ResNet-18 model.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
    """
    se_kwargs = kwargs.pop( 'se_kwargs' )
    block = partial( BasicBlock , se_kwargs = se_kwargs )
    block.expansion = BasicBlock.expansion
    model = ResNet(block, [2, 2, 2, 2], **kwargs)
    if pretrained:
        d = torch.load( get_model_file('resnet18', root=root))
        d = warp_dict_fn( d )
        try:
            model.load_state_dict( d , strict = True )
        except Exception as e:
            print(e)
            print( "try load with strict = True failed , load with strict = False" )
            model.load_state_dict( d , strict = False )
    return model


def resnet34(pretrained=True, root='~/.gluoncvth/models', **kwargs):
    """Constructs a ResNet-34 model.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
    """
    se_kwargs = kwargs.pop( 'se_kwargs' )
    block = partial( BasicBlock , se_kwargs = se_kwargs )
    block.expansion = BasicBlock.expansion
    model = ResNet(block, [3, 4, 6, 3], **kwargs)
    if pretrained:
        d = torch.load( get_model_file('resnet34', root=root))
        d = warp_dict_fn( d )
        try:
            model.load_state_dict( d , strict = True )
        except Exception as e:
            print(e)
            print( "try load with strict = True failed , load with strict = False" )
            model.load_state_dict( d , strict = False )
    return model


def resnet50(pretrained=True, root='~/.gluoncvth/models', **kwargs):
    """Constructs a ResNet-50 model.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
    """
    se_kwargs = kwargs.pop( 'se_kwargs' )
    block = partial( Bottleneck , se_kwargs = se_kwargs )
    block.expansion = Bottleneck.expansion
    model = ResNet(block, [3, 4, 6, 3], **kwargs)
    if pretrained:
        d = torch.load( get_model_file('resnet50', root=root))
        d = warp_dict_fn( d )
        try:
            model.load_state_dict( d , strict = True )
        except Exception as e:
            print(e)
            print( "try load with strict = True failed , load with strict = False" )
            model.load_state_dict( d , strict = False )
    return model


def resnet101(pretrained=True, root='~/.gluoncvth/models', **kwargs):
    """Constructs a ResNet-101 model.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
    """
    se_kwargs = kwargs.pop( 'se_kwargs' )
    block = partial( Bottleneck , se_kwargs = se_kwargs )
    block.expansion = Bottleneck.expansion
    model = ResNet(Bottleneck, [3, 4, 23, 3], **kwargs)
    if pretrained:
        d = torch.load( get_model_file('resnet101', root=root))
        d = warp_dict_fn( d )
        try:
            model.load_state_dict( d , strict = True )
        except Exception as e:
            print(e)
            print( "try load with strict = True failed , load with strict = False" )
            model.load_state_dict( d , strict = False )
    return model


def resnet152(pretrained=True, root='~/.gluoncvth/models', **kwargs):
    """Constructs a ResNet-152 model.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
    """
    se_kwargs = kwargs.pop( 'se_kwargs' )
    block = partial( Bottleneck , se_kwargs = se_kwargs )
    block.expansion = Bottleneck.expansion
    model = ResNet(Bottleneck, [3, 8, 36, 3], **kwargs)
    if pretrained:
        d = torch.load( get_model_file('resnet152', root=root))
        d = warp_dict_fn( d )
        try:
            model.load_state_dict( d , strict = True )
        except Exception as e:
            print(e)
            print( "try load with strict = True failed , load with strict = False" )
            model.load_state_dict( d , strict = False )
    return model

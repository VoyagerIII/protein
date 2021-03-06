##################################################
#borrowed from https://github.com/nashory/pggan-pytorch
##################################################
import torch
import numpy as np
import torchvision.models as models
import utils as utils
import tensorflow as tf
#from tensorboardX import SummaryWriter
import os, sys
import importlib
from types import ModuleType
import datetime
from tqdm import tqdm
from time import time
from sklearn.metrics import f1_score

class LogParser:
    def __init__(self):
        self.t = time()

    def parse_log_dict( self,  log_dicts , epoch , lr , num_imgs , config):
        for tag in log_dicts:
            #d = { k:log_dicts[tag][k] for k in filter( lambda x : isinstance(log_dicts[tag][x],float) , log_dicts[tag] ) } 
            if 'f1_score_label' in log_dicts[tag]:
                log_dicts[tag]['macro_f1_score'] = f1_score( log_dicts[tag]['f1_score_label'] , log_dicts[tag]['f1_score_pred']  , average = 'macro' )
            #log_dicts[tag] = d

        t = time()
        log_msg = ""
        if config.train['lr_curve'] == 'normal':
        #if not config.train['use_cos_lr']:
            log_msg += "epoch {}  ,  lr {:.3e} {:.2f} imgs/s\n".format( epoch , lr ,  num_imgs / (t - self.t) )

        elif config.train['lr_curve'] in ['cos','cyclical','one_cycle']:
            bounds = config.train['lr_bounds']
            for idx in range(len(bounds) - 1):
                if bounds[idx] <= epoch and epoch < bounds[idx+1]:
                    break
            log_msg += "epoch {} , lr {:.3e} , lr_period [{},{}) {:.2f} imgs/s\n".format( epoch , config.train['lrs'][idx] , bounds[idx] , bounds[idx+1] ,  num_imgs / (t - self.t) )
        for tag in log_dicts:
            log_msg += "  {} : ".format(tag)
            log_dict = log_dicts[tag]
            for idx,k_v in enumerate(log_dict.items()):
                k,v = k_v
                if isinstance( v , float):
                    if 'err' in k:
                        k = k.replace('err','acc')
                        v = 1 - v
                    spec_list = ['err','acc','top']
                    if sum( [ word  in k for word in spec_list ] ):
                        log_msg += "{} {:.3%} {} ".format(k,v,',' if idx < len(log_dict) -1 else '\n')
                    else:
                        log_msg += "{} {:.5f} {} ".format(k,v,',' if idx < len(log_dict) -1 else '\n')
            if all( map( lambda x : x in log_dict , ['tp','tn','fp','fn']) ):
                tp = log_dict['tp'].sum(0).astype(np.float32)
                tn = log_dict['tn'].sum(0).astype(np.float32)
                fp = log_dict['fp'].sum(0).astype(np.float32)
                fn = log_dict['fn'].sum(0).astype(np.float32)
                '''
                print( "tp :" ,  tp )
                print( "tn :" ,  tn )
                print( "fp :" ,  fp )
                print( "fn :" ,  fn )
                '''
                p = log_dict['precision'] = tp / (tp + fp  + 1e-8 )
                r = log_dict['recall'] = tp / (tp + fn + 1e-8 )
                log_dict['f1_score'] = (2 * p * r ) / ( p+r + 1e-8 )
                log_msg += "       precision "
                log_msg += np.array2string( log_dict['precision'] , formatter = {'float_kind':lambda x : "{:.2%}".format(x) }  ,max_line_width = 1000)
                log_msg += '\n'
                log_msg += "       recall "
                log_msg += np.array2string( log_dict['recall'] , formatter = {'float_kind':lambda x : "{:.2%}".format(x) } ,max_line_width = 1000)
                log_msg += '\n'
                log_msg += "       f1_score "
                log_msg += np.array2string( log_dict['f1_score'] , formatter = {'float_kind':lambda x : "{:.2%}".format(x) } ,max_line_width = 1000)
                log_msg += '\n'
        self.t = t
        return log_msg



class TensorBoardX:
    def __init__(self,config , log_dir , log_type = ['train','val','net'] ):
        os.system('mkdir -p {}'.format(log_dir))
        self.path = '{}'.format(log_dir )
        os.system('mkdir -p {}'.format(self.path))
        os.system('mkdir -p {}/{}'.format( self.path , 'models' ))
        print("Saving logs at {}".format(self.path))
        self.writer = {}
        for k in log_type:
            #self.writer[k] = SummaryWriter( self.path +'/' + k )
            self.writer[k] = tf.summary.FileWriter( self.path +'/' + k )


        #Export run arguments
        with open(os.path.join(self.path, 'run.txt'), 'wt') as f:
            f.write('%-16s%s\n' % ('Date', datetime.datetime.today()))
            f.write('%-16s%s\n' % ('Working dir', os.getcwd()))
            f.write('%-16s%s\n' % ('Executable', sys.argv[0]))
            f.write('%-16s%s\n' % ('Arguments', ' '.join(sys.argv[1:])))
        #Export config
        with open(os.path.join(self.path, 'config.txt'), 'wt') as fout:
            for k, v in sorted(config.__dict__.items()):
                if not k.startswith('_') and not isinstance( v , ModuleType ) :
                    fout.write("%s = %s\n" % (k, str(v)))
        self.logger = open( os.path.join(self.path,'log.txt') ,'w' )
        self.err_logger = open( os.path.join(self.path,'err.txt') ,'w' )

        #os.system('cp {} {}/'.format(config_filename , self.path))

    def tag(self,tag):
        return tag.replace('.','/')
                
    def add_scalar(self, tag, val, step , logtype):
        #self.writer[logtype].add_scalar(tag, val, step)
        tag=self.tag( tag )
        if isinstance(val,torch.Tensor):
            val = val.detach().cpu().numpy()
        summary = tf.Summary( value=[tf.Summary.Value(tag=tag,simple_value=val)] )
        self.writer[logtype].add_summary( summary , step )
        self.writer[logtype].flush()

    '''
    def add_scalars(self, tag, group_dict, step , logtype):
        self.writer[logtype].add_scalar(tag, group_dict, step)
    '''

    '''
    def add_image_grid(self, tag, ngrid, x, step , logtype):
        grid = utils.make_image_grid(x, ngrid)
        self.writer[logtype].add_image(tag, grid, step)
    '''
    def add_images(self, tag, images, step , logtype):
        """Log a list of images."""

        tag=self.tag(tag)
        img_summaries = []
        for i, img in enumerate(images):
            # Write the image to a string
            if isinstance(img , torch.Tensor):
                img = img.detach().cpu().numpy()
            s = BytesIO()
            scipy.misc.toimage(img).save(s, format="png")

            # Create an Image object
            img_sum = tf.Summary.Image(encoded_image_string=s.getvalue(),
                                       height=img.shape[0],
                                       width=img.shape[1])
            # Create a Summary value
            img_summaries.append(tf.Summary.Value(tag='%s/%d' % (tag, i), image=img_sum))

        # Create and write Summary
        summary = tf.Summary(value=img_summaries)
        self.writer[logtype].add_summary(summary, step)
        self.writer[logtype].flush()

    def add_histogram(self, tag, values, step, logtype, bins=1000):
        """Log a histogram of the tensor of values."""

        tag=self.tag(tag)
        # Create a histogram using numpy

        if isinstance(values , torch.Tensor):
            values = values.detach().cpu().numpy()
        counts, bin_edges = np.histogram(values, bins=bins)

        # Fill the fields of the histogram proto
        hist = tf.HistogramProto()
        hist.min = float(np.min(values))
        hist.max = float(np.max(values))
        hist.num = int(np.prod(values.shape))
        hist.sum = float(np.sum(values))
        hist.sum_squares = float(np.sum(values ** 2))

        # Drop the start of the first bin
        bin_edges = bin_edges[1:]

        # Add bin edges and counts
        for edge in bin_edges:
            hist.bucket_limit.append(edge)
        for c in counts:
            hist.bucket.append(c)

        # Create and write Summary
        summary = tf.Summary(value=[tf.Summary.Value(tag=tag, histo=hist)])
        self.writer[logtype].add_summary(summary, step)
        self.writer[logtype].flush()

    '''
    def add_image_single(self, tag, x, step , logtype):
        self.writer[logtype].add_image(tag, x, step)

    def add_histogram(self, tag , x , step , logtype):
        self.writer[logtype].add_histogram( tag , x , step )


    def add_graph(self, tag, x_input, model , logtype):
        torch.onnx.export(model, x_input, os.path.join(self.path, "{}.proto".format(tag)), verbose=True)
        self.writer[logtype].add_graph_onnx(os.path.join(self.path, "{}.proto".format(tag)))

    def export_json(self, out_file , logtype ):
        self.writer[logtype].export_scalars_to_json(out_file)
    '''
    def write_log(self , msg , end = '\n' , use_tqdm = True ):
        if use_tqdm:
            tqdm.write(msg, file=sys.stdout, end=end)
        else:
            print(msg,end=end,file=sys.stdout)
        self.logger.write( msg + end )
        sys.stdout.flush()
        self.logger.flush()
    def write_err(self , msg , end = '\n' ):
        sys.stderr.write( msg , end = end )
        self.err_logger.write( msg + end )
        sys.stderr.flush()
        self.err_logger.flush()
    def write_net(self , msg , silent = False):
        with open(os.path.join(self.path,'net.txt') , 'w') as fp:
            fp.write( msg +'\n' )
        if not silent:
            sys.stdout.write(msg+'\n')
            sys.stdout.flush()
 

def log_net_params(tb,net,epoch,epoch_length):
    for k,v in net.named_parameters():
        if v.requires_grad and v.grad is not None:
            try:
                tb.add_histogram( k , v , (epoch+1)*epoch_length , 'net' )
            except Exception as e:
                print( "{} is not finite".format(k)   )
                raise e
            try:
                tb.add_histogram( k+'_grad' , v.grad , (epoch+1)*epoch_length , 'net' )
            except Exception as e:
                print( "{}.grad is not finite".format(k)   )
                raise e


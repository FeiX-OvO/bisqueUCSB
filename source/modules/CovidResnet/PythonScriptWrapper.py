import sys
import io
from lxml import etree
import optparse
import logging
import os
# It is importing from source

logging.basicConfig(filename='PythonScript.log', filemode='a', level=logging.DEBUG) 
log = logging.getLogger('bq.modules')

from bqapi.comm import BQCommError
from bqapi.comm import BQSession
from bqapi.util import fetch_blob

from predict import predict_label_fake as predict_label


class ScriptError(Exception):
    def __init__(self, message):
        self.message = "Script error: %s" % message
    def __str__(self):
        return self.message

class PythonScriptWrapper(object):
    
    def preprocess(self, bq):

        log.info('Options: %s' % (self.options))
        """
        1. Get the resource image
        """
        self.image = bq.load(self.options.resourceURL)
        self.image_name=self.image.__dict__['name']
        log.info("process image as %s" % (self.image_name))
        log.info("image meta: %s" % (self.image))
        cwd= os.getcwd()
        result = fetch_blob(bq, self.options.resourceURL, dest=os.path.join(cwd,self.image_name))

        
        if '.gz' in self.image_name:
            os.rename(self.image_name,self.image_name.replace('.gz',''))
            self.image_name=self.image_name.replace('.gz','')

    def run(self):
        """
        Run Python script

        """
        bq = self.bqSession
        try:
            bq.update_mex('Pre-process the images')
            self.preprocess(bq)
        except (Exception, ScriptError) as e:
            log.exception("Exception during preprocess")
            bq.fail_mex(msg = "Exception during pre-process: %s" % str(e))

            return
        #call script
        z, covid, pna, normal= predict_label(log, self.image_name)

        self.bqSession.update_mex( 'Returning results')

        log.info('Total number of slices:{}.\nNumber of slices predicted as Covid:{}.\nNumber of slices predicted as PNA: {}\nNumber of slices predicted as Normal:{}'.format(z, covid, pna, normal))
        self.output_resources.append([self.image_name, z, covid, pna, normal])


    def setup(self):
        """
        Pre-run initialization

        """

        self.bqSession.update_mex('Initializing...')
        self.mex_parameter_parser(self.bqSession.mex.xmltree)
        self.output_resources = []


    def teardown(self):
##        """
##        Post the results to the mex xml
##        """
        self.bqSession.update_mex( 'Returning results')
        
        outputTag = etree.Element('tag', name ='outputs')
        outputTag.set('filemname',self.output_resources[0][0])
        outputTag.set('depth',str(self.output_resources[0][1]))
        print(etree.tostring(outputTag))
        log.debug('Output Mex results: %s'%(outputTag))
        self.bqSession.finish_mex(tags=[outputTag])
    

    def mex_parameter_parser(self, mex_xml):
        """
            Parses input of the xml and add it to options attribute (unless already set)

            @param: mex_xml
        """
        # inputs are all non-"script_params" under "inputs" and all params under "script_params"
        mex_inputs = mex_xml.xpath('tag[@name="inputs"]/tag[@name!="script_params"] | tag[@name="inputs"]/tag[@name="script_params"]/tag')
        if mex_inputs:
            for tag in mex_inputs:
                if tag.tag == 'tag' and tag.get('type', '') != 'system-input': #skip system input values
                    if not getattr(self.options,tag.get('name', ''), None):
                        log.debug('Set options with %s as %s'%(tag.get('name',''),tag.get('value','')))
                        setattr(self.options,tag.get('name',''),tag.get('value',''))
        else:
            log.debug('No Inputs Found on MEX!')

    def validate_input(self):
        """
            Check to see if a mex with token or user with password was provided.

            @return True is returned if validation credention was provided else
            False is returned
        """
        if (self.options.mexURL and self.options.token): #run module through engine service
            return True
        if (self.options.user and self.options.pwd and self.options.root): #run module locally (note: to test module)
            return True
        log.debug('Insufficient options or arguments to start this module')
        return False



    def main(self):
        parser = optparse.OptionParser()
        parser.add_option('--mex_url'         , dest="mexURL")
        parser.add_option('--module_dir'      , dest="modulePath")
        parser.add_option('--staging_path'    , dest="stagingPath")
        parser.add_option('--bisque_token'    , dest="token")
        parser.add_option('--user'            , dest="user")
        parser.add_option('--pwd'             , dest="pwd")
        parser.add_option('--root'            , dest="root")
        parser.add_option('--resource_url'    , dest="resourceURL")
        
            
        (options, args) = parser.parse_args()

        
        fh = logging.FileHandler('scriptrun.log', mode='a')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('[%(asctime)s] %(levelname)8s --- %(message)s ' +
                                  '(%(filename)s:%(lineno)s)',datefmt='%Y-%m-%d %H:%M:%S')
        fh.setFormatter(formatter)
        log.addHandler(fh)
        

        try: #pull out the mex

            if not options.resourceURL:
                options.resourceURL=sys.argv[1]
            if not options.mexURL:
                options.mexURL = sys.argv[2]
            if not options.token:
                options.token = sys.argv[3]
        except IndexError: #no argv were set
            pass

        if not options.stagingPath:
            options.stagingPath = ''

        log.debug('\n\nPARAMS : %s \n\n Options: %s' % (args, options))
        self.options = options

        if self.validate_input():

             #initalizes if user and password are provided
            if (self.options.user and self.options.pwd and self.options.root):

                try:
                    self.bqSession = BQSession().init_local( self.options.user, self.options.pwd, bisque_root=self.options.root)
                    self.options.mexURL = self.bqSession.mex.uri

                except:
                    return

             #initalizes if mex and mex token is provided
            elif (self.options.mexURL and self.options.token):

                try:
                    self.bqSession = BQSession().init_mex(self.options.mexURL, self.options.token)
                except:
                    return



            else:
                raise ScriptError('Insufficient options or arguments to start this module')

            try:
                self.setup()
            except Exception as e:
                log.exception("Exception during setup")
                self.bqSession.fail_mex(msg = "Exception during setup: %s" %  str(e))
                return
####
            try:
                self.run()
            except (Exception, ScriptError) as e:
                log.exception("Exception during run")
                self.bqSession.fail_mex(msg = "Exception during run: %s" % str(e))
                return
##
            try:                
                self.teardown()
            except (Exception, ScriptError) as e:
                log.exception("Exception during teardown")
                self.bqSession.fail_mex(msg = "Exception during teardown: %s" %  str(e))
                return
        
            self.bqSession.close()
        log.debug('Session Close')
        
if __name__=="__main__":
    PythonScriptWrapper().main()

#!/usr/bin/env python

import re
import os
import sys
import yaml
import argparse
import json
import execjs

class CWL_Input:
    def __init__(self, doc):
        self.doc = doc
    
    def get_pos(self):
        if 'inputBinding' in self.doc:
            return self.doc['inputBinding'].get('position', 100000)
        return 100000
    
    def get_id(self):
        return self.doc['id']
    
    def is_optional(self):
        if isinstance(self.doc['type'], list) and 'null' in self.doc['type']:
            return True
        return False
    
    def get_arg(self, data):
        if self.is_optional and self.doc['id'] not in data:
            return []
        a = self.format_arg(self.doc['type'], data[self.doc['id']])
        if 'inputBinding' in self.doc:
            if 'itemSeparator' in self.doc['inputBinding']:
                a = [ self.doc['inputBinding']['itemSeparator'].join(a) ]
            if 'prefix' in self.doc['inputBinding']:
                if isinstance(a[0], bool):
                    return [ self.doc['inputBinding']['prefix'] ]
                a = [self.doc['inputBinding']['prefix']] + a
            return a
        return []
    
    def format_arg(self, format, data):
        if isinstance(format, basestring):
            if format == "File":
                return [data['path']]
            elif format == "int":
                return ["%d" % (data)]
            elif format ==  "boolean":
                return [ data ]
            else:
                raise Exception("Unknown Format: %s" % (format))
        elif isinstance(format, list):
            o = None
            for t in format:
                if t != "null":
                    o = self.format_arg(t, data)
            return o
        else:
            if format['type'] == 'array':
                o = []
                for a in data:
                    i = self.format_arg(format['items'], a)
                    if 'inputBinding' in format and 'prefix' in format['inputBinding']:
                        o.append(format['inputBinding']['prefix'])
                    o.extend(i)
                return o
            else:
                raise Exception("Unknown Format: %s" % (format['type']))

    def cmp_pos(self, other):
        if other.get_pos() == self.get_pos():
            if isinstance(other, CWL_Argument):
                return 1
            if self.get_id() > other.get_id():
                return 1
            else:
                return -1
            return 0
        if other.get_pos() > self.get_pos():
            return -1
        else:
            return 1
            
class CWL_Argument:
    def __init__(self, doc):
        self.doc = doc
    
    def get_value(self):
        #TODO: Put actual evaluation here
        if 'valueFrom' in self.doc:
            vf = self.doc['valueFrom']
            if vf == "$(runtime.cores)":
                return "4"
            else:
                raise Exception("Unable to evaluate")
    
    def get_arg(self, data):
        if isinstance(self.doc, basestring):
            return self.doc
        v = self.get_value()
        if 'prefix' in self.doc:
            if isinstance(v, bool):
                return [ self.doc['prefix'] ]
            return [ self.doc['prefix'], v ]
        return [ v ]
    
    def get_pos(self):
        if isinstance(self.doc, basestring):
            return 100000
        return self.doc.get('position', 100000)
    
    def cmp_pos(self, other):
        if other.get_pos() == self.get_pos():
            if isinstance(other, CWL_Input):
                return -1
            return 0
        if other.get_pos() > self.get_pos():
            return -1
        else:
            return 1


class CWL_CommandLineTool:
    def __init__(self, doc):
        self.doc = doc
    
    def get_command_line(self, data):
        cmd = self.get_base_command()
        for a in self.get_inputs():
            cmd.extend( a.get_arg(data) )
        return cmd
    
    def get_stdout(self):
        return self.doc.get('stdout', None)
    
    def get_stdin(self):
        return self.doc.get("stdin", None)
    
    def eval_expression(self, exp, data):
        if exp is None:
            return exp
        res = re.search("\$\((.*)\)", exp)
        if res:
            ctx = execjs.compile("inputs = %s" % (json.dumps(data)))
            return ctx.eval(res.group(1))
        else:
            return exp

    def get_base_command(self):
        if isinstance(self.doc['baseCommand'], basestring):
            return [self.doc['baseCommand']]
        return self.doc['baseCommand']
    
    def get_inputs(self):
        out = []
        for a in self.doc['inputs']:
            out.append( CWL_Input(a) )
        for a in self.doc.get('arguments', []):
            out.append( CWL_Argument(a) )
            
        out = sorted( out, lambda x,y: x.cmp_pos(y) )
        #for a in out:
        #    print a.get_pos()
        return out
    
CWL_OBJ_MAP = {
    'CommandLineTool' : CWL_CommandLineTool
}


class CWLDoc:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        
    def parse(self):
        with open(self.path) as handle:
            obj = yaml.load(handle.read())
        
        if obj['class'] in CWL_OBJ_MAP:
            out = CWL_OBJ_MAP[obj['class']]( obj )
            return out
    

def adjust_input_paths(data, basepath):
    if isinstance(data, dict):
        if 'class' in data and data['class'] == 'File':
            data['path'] = os.path.join(basepath, data['path'])
        else:
            for v in data.values():
                adjust_input_paths(v, basepath)
    elif isinstance(data, list):
        for i in data:
            adjust_input_paths(i, basepath)

def main():
    parser = argparse.ArgumentParser()
        
    parser.add_argument("--conformance-test", action="store_true", default=False)
    parser.add_argument("--quiet", action="store_true", default=False)
    parser.add_argument("--no-container", action="store_true", default=False)
    parser.add_argument("--basedir", default="./")
    parser.add_argument("--outdir", default="./")
    parser.add_argument("--tmpdir-prefix=", default="cwl_")
    parser.add_argument("--tmp-outdir-prefix=", default="cwl_")
    parser.add_argument("--version", action="store_true", default=False)
    parser.add_argument("cwldoc", nargs="?")
    parser.add_argument("input", nargs="?")
    
    args = parser.parse_args()
    
    if args.version:
        print sys.argv[0], "0.1"
        return
        
    if args.conformance_test:
        cwldoc = CWLDoc(args.cwldoc)
        cwl_cmd = cwldoc.parse()
        with open(args.input) as handle:
            input_data = json.loads(handle.read())        
        adjust_input_paths(input_data, os.path.dirname(args.input))        
        out = {
            "args" : cwl_cmd.get_command_line(input_data), 
            "stdout" : cwl_cmd.get_stdout(),
            "stdin" : cwl_cmd.eval_expression(cwl_cmd.get_stdin(), input_data)
        }
        print json.dumps(out)
        return

    cwldoc = CWLDoc(args.cwldoc)
    cwl_cmd = cwldoc.parse()
    with open(args.input) as handle:
        input_data = json.loads(handle.read())
    adjust_input_paths(input_data, os.path.dirname(args.input))
    
    print "Running", cwl_cmd.get_command_line(input_data)

if __name__ == "__main__":
    main()
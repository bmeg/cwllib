#!/usr/bin/env python

import parsley
import re
import sys
import yaml

cwilGrammar = """
document = ws expr_list:x ws -> CWILDoc(x)

expr_list = expr:x (
    ws expr_list:y -> [x] + y 
    | -> [x]
)

expr = (
    'task' bs task_block:x -> x 
    | 'workflow' bs workflow_block:x -> x
)

#Parsing tasks
task_block = word:name optbs '{' ws task_part_list:parts ws '}' -> CWILTask(name, parts)
task_part_list = task_part:x (
    newlines task_part_list:y -> [x] + y
    | -> [x]
)
task_part = optbs (command_block|input_block|output_block|import_block):x -> x

#Parsing the import statements
import_block = 'import' bs path_word:x -> CWILImport(x)

input_block = input_declare:x (
    newlines input_block:y -> [x] + y
    | -> [x]
):z -> CWILInputSet(z)

input_declare = var_type:vt bs word:vn -> CWILInputDeclare(vn, vt)

var_type = ("File"):x -> CWILVariableType(x)

#Parsing command lines
command_block = 'command' optbs '{' command_line:x '}' -> x
command_line = ws command_arg_list:x ws -> CWILCommandLine(x)
command_arg_list = command_arg:x (
    bs command_arg_list:y -> [x] + y
    | -> [x]
)
command_arg = (
    symbol_word|quote_word|variable
):x -> x

variable = '${' optbs (
    #word:y bs word:x -> CWILVariable(y, x)
    #| 
    word:x -> CWILVariableUse(x) 
):z optbs '}' -> z

#Parsing output declarations
output_block = 'output' optbs '{' ws output_declare_list:outputs ws '}' -> CWILOutputSet(outputs)
output_declare_list = output_declare:x (
    newlines output_declare_list:y -> [x] + y
    | -> [x]
)
output_declare = word:output_type bs word:output_name bs '=' bs output_arg:arg -> CWILOutputDeclare(output_name, output_type, arg)
output_arg = function

function = word:name '(' optbs (
    function:x -> x
    | -> None
):arg optbs ')'-> CWILFunction(name, arg)

#Parsing Workflow
workflow_block = word:name optbs '{' ws workflow_command_list:commands ws '}' -> CWILWorkflow(name, commands)
workflow_command_list = workflow_command:x (
    newlines optbs workflow_command_list:y -> [x] + y
    | -> [x]
)

workflow_command = "call" bs word:x (
    ws input_def:y -> y
    | -> None 
):z -> CWILTaskCall(x,z)
input_def = '{' ws 'input:' optbs declaration:x ws '}' -> x

declaration = word:x optbs '=' symbol_word:y -> CWILDeclaration(x,y)

#Different types of whitespaces
newlines = '\n'+
bs = ' '+
optbs = ' '*
quote_word = "'" not_quote*:x "'" -> "".join(x)
not_quote = anything:x ?(x != "'") -> x
not_dquote = anything:x ?(x != '"') -> x

ws = (' '|'\n'|'\t')*
word = alphanum+:x -> "".join(x)
alphanum = anything:x ?(re.search(r'\w', x) is not None) -> x

symbol_word = symbol_alphanum+:x -> "".join(x)
symbol_alphanum = anything:x ?(re.search(r'[\w\-\|\.]', x) is not None) -> x

path_word = path_alphanum+:x -> "".join(x)
path_alphanum = anything:x ?(re.search(r'[\w\-\/|\.]', x) is not None) -> x
"""

class CWILDoc:
    def __init__(self, statements):
        self.statements = statements
        
    def to_cwl(self):
        
        
        workflow = None
        for w in self.statements:
            if w.type == 'workflow':
                workflow = w
        if workflow is None:
            for w in self.statements:
                if w.type == 'task':
                    return w.to_cwl()
        else:
            out = {
                "class" : "Workflow",
                "steps" : []
            }
            for s in workflow.commands:
                out['steps'].append( s.to_cwl(self) )
            return out
    
    def get_task(self, name):
        for i in self.statements:
            if i.type == 'task' and i.name == name:
                return i
        return None

class CWILTask:
    def __init__(self, name, parts):
        self.type = 'task'
        self.name = name
        self.part_map = {}

        for part in parts:
            if part.type in self.part_map:
                raise Exception("Previously declared: %s" % (part.type))
            self.part_map[part.type] = part

    def to_cwl(self):
        input_map = {}
        if 'input_set' in self.part_map:
            for i in self.part_map['input_set'].inputs:
                input_map[i.name] = {
                    'id' : i.name,
                    'type' : i.type.to_cwl()
                }
        baseCommand = None
        if 'command_line' in self.part_map:
            baseCommand = self.part_map['command_line'].args[0]
            pos = 0
            for a in self.part_map['command_line'].args[1:]:
                if isinstance(a, CWILVariableUse):
                    input_map[a.name]['inputBinding'] = {
                        'position' : pos
                    }
                pos += 1
        inputs = input_map.values()
        
        out = {
            "class" : "CommandLineTool",
            "id" : "%s" % (self.name),
            "baseCommand" : baseCommand,
            "inputs" : inputs,
            "outputs" : []
        }
        if 'import' in self.part_map:
            print "Importing", self.part_map['import'].path
            with open(self.part_map['import'].path) as handle:
                import_text = handle.read()
            doc = PARSER(import_text).document()
            for k,v in doc.to_cwl().items():
                out[k] = v
        return out
            
class CWILImport:
    def __init__(self, path):
        self.type = "import"
        self.path = path

class CWILCommandLine:
    def __init__(self, args):
        self.type = 'command_line'
        self.args = args
        #print "Command line:", self.args

class CWILDeclaration:
    def __init__(self, dest, value):
        self.dest = dest
        self.value = value

class CWILVariableType:
    def __init__(self, var_type):
        self.var_type = var_type
    
    def to_cwl(self):
        return self.var_type
        
class CWILVariable:
    def __init__(self, var_type, name):
        self.var_type = var_type
        self.name = name

class CWILVariableUse:
    def __init__(self, name):
        self.name = name
    
    def to_cwl(self):
        return self.name

class CWILInputSet:
    def __init__(self, inputs):
        self.type = "input_set"
        self.inputs = inputs

class CWILOutputSet:
    def __init__(self, outputs):
        self.type = 'output_set'
        self.outputs = outputs

class CWILWorkflow:
    def __init__(self, name, commands):
        self.type = 'workflow'
        self.commands = commands

class CWILTaskCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args
    
    def to_cwl(self, cwil_doc):
        return cwil_doc.get_task(self.name).to_cwl()

class CWILInputDeclare:
    def __init__(self, name, type):
        self.type = 'input_declare'
        self.name = name
        self.type = type

class CWILOutputDeclare:
    def __init__(self, name, type, arg):
        self.name = name
        self.type = type
        self.arg = arg

class CWILFunction:
    def __init__(self, name, arg):
        self.name = name
        self.arg = arg

PARSER = parsley.makeGrammar(cwilGrammar, {
    're': re,
    'CWILDoc' : CWILDoc,
    'CWILImport' : CWILImport,
    'CWILWorkflow' : CWILWorkflow,
    'CWILTaskCall' : CWILTaskCall,
    'CWILTask' : CWILTask,
    'CWILInputSet' : CWILInputSet,
    'CWILOutputSet' : CWILOutputSet,
    'CWILCommandLine' : CWILCommandLine,
    'CWILVariable' : CWILVariable,
    'CWILVariableUse' : CWILVariableUse,
    'CWILVariableType' : CWILVariableType,
    'CWILInputDeclare' : CWILInputDeclare,
    'CWILOutputDeclare' : CWILOutputDeclare,
    'CWILDeclaration' : CWILDeclaration,
    'CWILFunction' : CWILFunction
})

if __name__ == "__main__":
    
    with open(sys.argv[1]) as handle:
        doc_text = handle.read()
    
    doc = PARSER(doc_text).document()
    print yaml.dump(doc.to_cwl(), default_flow_style=False)
    
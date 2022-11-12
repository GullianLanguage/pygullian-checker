from dataclasses import dataclass
from gullian_parser.lexer import Name
from gullian_parser.parser import Ast, TypeDeclaration, FunctionDeclaration, Attribute

@dataclass
class Type:
    name: Name
    fields: dict[str, "Type"]
    functions: dict[str, FunctionDeclaration]
    declaration: TypeDeclaration
    module_name: str="global"

    def __repr__(self):
        return f'Type({self.name})'
    
    def import_field(self, name: Name | Attribute):
        type_fields = dict(self.fields)

        if type(name) is Name:
            if name in type_fields:
                return type_fields[name]
            
            raise AttributeError(f"{name.format} is not a field of type {self.name.format}. at line {name.line}, in module {self.module_name}")
    
        elif type(name) is Attribute:
            if name.left in type_fields:
                return type_fields[name.left].import_field(name.right)
            
        raise AttributeError(f"{name.left.format} is not a field of type {self.name.format}. at line {name.line}, in module {self.module_name}")

    def import_function(self, name: Name | Attribute):
        type_fields = dict(self.fields)

        if type(name) is Name:
            if name in self.functions:
                return self.functions[name]
            
            raise AttributeError(f"{name.format} is not a function of type {self.name.format}. at line {name.line}, in module {self.module_name}")
    
        elif type(name) is Attribute:
            if name.left in type_fields:
                return type_fields[name.left].import_function(name.right)
            
        raise AttributeError(f"{name.left.format} is not a field of type {self.name.format}. at line {name.line}, in module {self.module_name}")
    
    @property
    def format(self):
        return self.name.format

    @classmethod
    def new(cls, name: str | Name, declaration: TypeDeclaration=None):
        if type(name) is str:
            return cls(Name(name), dict(), dict(), declaration)

        return cls(name, dict(), dict(), declaration)

@dataclass
class Typed:
    ast: Ast
    type: Type

@dataclass
class GenericType:
    name: str
    parameters: tuple[str]
    declaration: TypeDeclaration

VOID = Type.new('void')
BOOL = Type.new('bool')
INT = Type.new('int')
FLOAT = Type.new('float')
STR = Type.new('str')
FUNCTION = Type.new('function')

BASIC_TYPES = {
    'void': VOID,
    'bool': BOOL,
    'int': INT,
    'float': FLOAT,
    'str': STR,
    'function': FUNCTION
}

@dataclass
class Context:
    module: "Module"
    variables: dict[str, Type]
    functions: dict[str, FunctionDeclaration]

    @classmethod
    def new(cls):
        return cls(dict())
    
    def import_variable(self, name: Name | Attribute):
        if type(name) is Name:
            if name in self.variables:
                return self.variables[name]
            
            raise AttributeError(f"{name.left.format} is not a variable of the current scope. at line {name.line}, in module {self.module.name}")
        elif type(name) is Attribute:
            if type(name.left) is Attribute:
                return self.import_variable(name.left).import_field(name.right)

            if name.left in self.variables:
                return self.variables[name.left].import_field(name.right)
            
        raise AttributeError(f"{name.left.format} is not a variable of the current scope. at line {name.line}, in module {self.module.name}")

    def import_function(self, name: Name | Attribute):
        if type(name) is Name:
            if name in self.functions:
                return self.functions[name]
            
            raise AttributeError(f"{name.left.format} is not a function of the current scope. at line {name.line}, in module {self.module.name}")
        elif type(name) is Attribute:
            if type(name.left) is Attribute:
                return self.import_variable(name.left).import_function(name.right)

            if name.left in self.variables:
                return self.variables[name.left].import_function(name.right)
            
            raise AttributeError(f"{name.left.format} is not an variable of the current scope. at line {name.line}, in module {self.module.name}")
        
        return self.module.import_function(name)

@dataclass
class Module:
    name: str
    types: dict[str, Type]
    functions: dict[str, FunctionDeclaration]
    imports: dict[str, "Module"]

    @classmethod
    def new(cls, name: str):
        return cls(name, dict(), dict(), dict())

    def import_type(self, name: Name | Attribute):
        if type(name) is Name:
            if name in BASIC_TYPES:
                return BASIC_TYPES[name]
            
            if name in self.types:
                return self.types[name]
            
            raise NameError(f"{name.format} is not a type of module {self.name}. at line {name.line}")
        elif type(name) is Attribute:
            if name.left in self.imports:
                return self.imports[name.left].import_type(name.right)
            
            raise NameError(f'{name.left} is not an import of module {self.name}. at line {name.line}')
        
        raise TypeError(f'{name} must be either Name, or Attribute. got {name}. at line {name.line}, in module {self.name}')
    
    def import_function(self, name: Name | Attribute):
        if type(name) is Name:
            return self.functions[name]
        elif type(name) is Attribute:
            if name.left in self.imports:
                return self.imports[name.left].import_function(name.right)
            elif name.left in self.types:
                return self.types[name.left].import_function(name.right)
            
            raise NameError(f'{name.left} is not an import of module {self.name}. at line {name.line}')
        
        raise TypeError(f'{name} must be either Name, or Attribute. got {name}. at line {name.line}, in module {self.name}')
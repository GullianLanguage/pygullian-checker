from dataclasses import dataclass
import os

from gullian_parser.source import Source
from gullian_parser.lexer import *
from gullian_parser.parser import *

from .module import *

@dataclass
class Checker:
    module: Module
    context: Context
    
    def check_type_compatibility(self, left: Type, right: Type, *, swap_order=True):
        if type(left) is not Type:
            raise TypeError(f"left must be a Type, got {left}. at line {left.line}, in module {self.module.name}")
        elif type(right) is not Type:
            raise TypeError(f"right must be a Type, got {left}. at line {left.line}, in module {self.module.name}")
        
        if type(left.name) is Subscript:
            if left.name == right.name:
                return True

        if left == right:
            return True

        if left is PTR:
            if right is INT:
                return True
            elif right is STR:
                return True
        
        if swap_order:
            return self.check_type_compatibility(right, left, swap_order=False)
        
        return False

    def check_struct_literal(self, struct_literal: StructLiteral):
        type_ =  self.module.import_type(struct_literal.name)

        struct_literal.arguments = [self.check_expression(argument) for argument in struct_literal.arguments]

        # If its type is a union, treat it like a union literal
        if type(type_.declaration) is UnionDeclaration:
            if len(struct_literal.arguments) > 1:
                raise IndexError(f"too many fields to union literal '{struct_literal.format}', expected 1, got {len(struct_literal.arguments)}. at line {struct_literal.line}, in module {self.module.name}")
            elif len(struct_literal.arguments) < 1:
                raise IndexError(f"too few fields to union literal '{struct_literal.format}', expected 1, got {len(struct_literal.arguments)}. at line {struct_literal.line}, in module {self.module.name}")
            
            argument = struct_literal.arguments[0]
            any_type_compatible = False

            for field_name, field_type in type_.fields:
                if self.check_type_compatibility(argument.type, field_type):
                    any_type_compatible = True
                    break
            
            if not any_type_compatible:
                raise NameError(f"type mismatch. union literal '{struct_literal.format}' expects: {', '.join(type_.format for type_ in type_.fields)}, got {argument.type.format}. at line {argument.line}, in module {self.module.name}")

            return Typed(struct_literal, type_)
        
        # Treat like a normal union literal
        if len(struct_literal.arguments) > len(type_.fields):
            raise IndexError(f"too many fields to struct literal '{struct_literal.format}', expected {len(type_.fields)}, got {len(struct_literal.arguments)}. at line {struct_literal.line}, in module {self.module.name}")
        elif len(struct_literal.arguments) < len(type_.fields):
            raise IndexError(f"too few fields to struct literal '{struct_literal.format}', expected {len(type_.fields)}, got {len(struct_literal.arguments)}. at line {struct_literal.line}, in module {self.module.name}")
        
        for argument, (field_name, field_type) in zip(struct_literal.arguments, type_.fields):
            if not self.check_type_compatibility(argument.type, field_type):
                raise NameError(f"type mismatch. struct literal '{struct_literal.format}' parameter '{field_name.format}' expects {field_type.format}, got {argument.type.format}. at line {argument.line}, in module {self.module.name}")

        return Typed(struct_literal, type_)

    def check_call(self, call: Call):
        if call.generic:
            function = self.context.import_function(Subscript(call.name, tuple(self.module.import_type(hint) for hint in call.generic)))
        else:
            function = self.context.import_function(call.name)
        
            if type(function) is GenericFunction:
                raise TypeError(f"This function is generic, you must pass its type arguments in '{call.format}'. at line {call.line}, in module {self.module.name}")

        if type(function) is AssociatedFunction:
            if type(call.name) is Attribute:
                call.arguments.insert(0, call.name.left)

        if len(call.arguments) > len(function.declaration.head.parameters):
            raise IndexError(f"too many arguments to function '{call.format}', expected {len(function.declaration.head.parameters)}, got {len(call.arguments)}. at line {call.line}, in module {self.module.name}")
        elif len(call.arguments) < len(function.declaration.head.parameters):
            raise IndexError(f"too few arguments to function '{call.format}', expected {len(function.declaration.head.parameters)}, got {len(call.arguments)}. at line {call.line}, in module {self.module.name}")
        
        call.arguments = [self.check_expression(argument) for argument in call.arguments]

        for argument, (parameter_name, parameter_type) in zip(call.arguments, function.head.parameters):
            if not self.check_type_compatibility(argument.type, parameter_type):
                raise NameError(f"type mismatch. function '{call.format}' parameter '{parameter_name.format}' expects {parameter_type.format}, got {argument.type.format}. at line {argument.line}, in module {self.module.name}")

        return Typed(call, function.declaration. head.return_hint)
    
    # NOTE: May cause issues, it only works for variables
    def check_attribute(self, attribute: Attribute):
        variable_type = self.context.import_variable(attribute.left)
        variable_type_fields = dict(variable_type.fields)

        if attribute.right not in variable_type_fields:
            raise NameError(f'{attribute.right.format} is not a field of type {variable_type.name.format}, at line {attribute.line}, in module {self.module.name}')
        
        if type(variable_type.declaration) is UnionDeclaration:
            if attribute not in self.context.guards:
                raise AttributeError(f"Acessing union field '{attribute.format}' directly is not allowed, you must check if its initialized first. at line {attribute.line}, in module {self.module.name}")

        return Typed(attribute, variable_type_fields[attribute.right])
    
    def check_binary_operator(self, binary_operator: BinaryOperator):
        binary_operator.left = self.check_expression(binary_operator.left)
        binary_operator.right = self.check_expression(binary_operator.right)

        if not self.check_type_compatibility(binary_operator.left.type, binary_operator.right.type):
            raise TypeError(f'types for {binary_operator.format} must be compatible. expected {binary_operator.left.type.format}, got {binary_operator.right.type.format}. at line {binary_operator.line}, in module {self.module.name}')

        if binary_operator.operator.kind in TOKENKIND_LOGICOPERATORS:
            return Typed(binary_operator, BOOL)
        elif binary_operator.operator.kind in TOKENKIND_NUMERICOPERATORS:
            return Typed(binary_operator, binary_operator.left.type)

        raise NotImplementedError(f"bug(checker): checking for binary operator {binary_operator.format} is not implemented yet. at line {binary_operator.line}, in module {self.module.name}") 

    def check_unary_operator(self, unary_operator: UnaryOperator):
        unary_operator.expression = self.check_expression(unary_operator.expression)

        if unary_operator.operator.kind is TokenKind.Ampersand:
            return Typed(unary_operator, new_ptr_for(unary_operator.expression.type))

        raise NotImplementedError(f"bug(checker): checking for unary operator {unary_operator.format} is not implemented yet. at line {unary_operator.line}, in module {self.module.name}")
    
    def check_test_guard(self, test_guard: TestGuard):
        return Typed(test_guard, BOOL)
    
    def check_expression(self, expression: Expression):
        if type(expression) is Literal:
            if type(expression.value) is str:
                return Typed(expression, STR)
            elif type(expression.value) is int:
                return Typed(expression, INT)
            elif type(expression.value) is float:
                return Typed(expression, FLOAT)

            raise NotImplementedError(f'checker(bug): checking for literal {expression.format} is not implemented yet. at line {expression.line}, in module {self.module.name}')

        if type(expression) is Name:
            if expression in self.context.variables:
                return Typed(expression, self.context.variables[expression])
            
            raise NameError(f"{expression.format} is not a variable. at line {expression.line}, in module {self.module.name}")
        elif type(expression) is Attribute:
            return self.check_attribute(expression)
        elif type(expression) is StructLiteral:
            return self.check_struct_literal(expression)
        elif type(expression) is Call:
            return self.check_call(expression)
        elif type(expression) is UnaryOperator:
            return self.check_unary_operator(expression)
        elif type(expression) is BinaryOperator:
            return self.check_binary_operator(expression)
        elif type(expression) is TestGuard:
            return self.check_test_guard(expression)
        
        raise NotImplementedError(f"bug(checker): checking for {expression.format} is not implemented yet. at line {expression.line}, in module {self.module.name}")
    
    def check_variable_declaration(self, variable_declaration: VariableDeclaration):
        variable_declaration.value = self.check_expression(variable_declaration.value)
        self.context.variables[variable_declaration.name.format] = variable_declaration.value.type

        return variable_declaration
    
    def check_if(self, if_: If):
        if_.condition = self.check_expression(if_.condition)

        # Add guard
        if type(if_.condition.ast) is TestGuard:
            self.context.guards.add(if_.condition.ast.expression)

        if_.true_body = self.check_body(if_.true_body)

        # Remove guard
        if type(if_.condition.ast) is TestGuard:
            self.context.guards.remove(if_.condition.ast.expression)

        if if_.false_body:
            if_.false_body = self.check_body(if_.false_body)
        
        return if_
    
    def check_return(self, return_: Return):
        return_.value = self.check_expression(return_.value)

        return return_

    def check_body(self, body: Body):
        def check(ast: Ast):
            if type(ast) is VariableDeclaration:
                return self.check_variable_declaration(ast)
            elif type(ast) is Call:
                return self.check_call(ast)
            elif type(ast) is If:
                return self.check_if(ast)
            elif type(ast) is Return:
                return self.check_return(ast)
            
            raise NotImplementedError(f"bug(checker): checking for {ast.format} is not implemented yet. at line {ast.line}, in module {self.module.name}")

        body.lines = [check(line) for line in body.lines]

        return body
    
    def check_import(self, import_: Import):
        filepath = import_.module_name.format.replace('.', os.sep) + '.gullian'

        if not os.path.exists(filepath):
            raise ImportError(f"can't import '{import_.module_name.format}', file '{filepath}' does not exists.")
        
        module = Module.new(import_.module_name.format)
        checker = Checker.new(module)

        tokens = tuple(Lexer(Source(open(filepath).read()), module.name).lex())
        asts = tuple(Parser(Source(tokens), module.name).parse())

        for _ in checker.check(asts):
            continue

        self.module.imports[import_.module_name.rightest] = module

        return import_
    
    def check_union_declaration(self, union_declaration: UnionDeclaration):
        # If union is generic we dont perform checking just store it
        if union_declaration.generic:
            generic_union_type = GenericType(union_declaration.name, union_declaration.generic, union_declaration, dict(), self.module)
            self.module.types[generic_union_type.name] = generic_union_type

            return generic_union_type
        
        union_declaration.fields = [(field_name, self.module.import_type(field_hint)) for field_name, field_hint in union_declaration.fields]
        
        union_type = Type(union_declaration.name, union_declaration.fields, dict(), union_declaration, self.module.name)
        self.module.types[union_type.name] = union_type

        return union_type

    def check_struct_declaration(self, struct_declaration: StructDeclaration):
        # If struct is generic we dont perform checking just store it
        if struct_declaration.generic:
            generic_struct_type = GenericType(struct_declaration.name, struct_declaration.generic, struct_declaration, dict(), self.module)
            self.module.types[generic_struct_type.name] = generic_struct_type

            return generic_struct_type
        
        struct_declaration.fields = [(field_name, self.module.import_type(field_hint)) for field_name, field_hint in struct_declaration.fields]
        
        struct_type = Type(struct_declaration.name, struct_declaration.fields, dict(), struct_declaration, self.module.name)
        self.module.types[struct_type.name] = struct_type

        return struct_type
    
    def check_extern(self, extern: Extern):
        if type(extern.head) is not FunctionHead:
            raise NotImplementedError(f"checker(bug): checking for '{extern.format}' is not implemented yet")
        
        extern.head.parameters = [(parameter_name, self.module.import_type(parameter_hint)) for parameter_name, parameter_hint in extern.head.parameters]
        extern.head.return_hint = self.module.import_type(extern.head.return_hint)

        function = Function(extern)
        self.module.functions[extern.head.name] = function

        return extern

    def check_function_declaration(self, function_declaration: FunctionDeclaration):
        # If function is generic, ignore for now
        if function_declaration.head.generic:
            # Check and assign the associated function
            if type(function_declaration.head.name) is Attribute:
                associated_type = self.module.import_type(function_declaration.head.name.left)
                associated_function = GenericFunction(function_declaration.head.generic, function_declaration, self.module)
                
                associated_type.functions[function_declaration.head.name.right] = associated_function

                return associated_function
            
            generic_function = GenericFunction(function_declaration.head.generic, function_declaration, self.module)
            self.module.functions[function_declaration.head.name] = generic_function

            return generic_function

        function_declaration.head.parameters = [(parameter_name, self.module.import_type(parameter_hint)) for parameter_name, parameter_hint in function_declaration.head.parameters]
        function_declaration.head.return_hint = self.module.import_type(function_declaration.head.return_hint)
        
        # Check and assign the associated function
        if type(function_declaration.head.name) is Attribute:
            associated_type = self.module.import_type(function_declaration.head.name.left)

            # Inject the parameters in checker variables
            checker = Checker(self.module, self.context.copy())

            for parameter_name, parameter_type in function_declaration.head.parameters:
                checker.context.variables[parameter_name] = parameter_type
            
            # Now check its body
            function_declaration.body = checker.check_body(function_declaration.body)

            # And finnaly submit it back
            associated_function = AssociatedFunction(associated_type, function_declaration)
            associated_type.functions[function_declaration.head.name.right] = associated_function

            return associated_function

        # Inject the parameters in checker variables
        checker = Checker(self.module, self.context.copy())

        for parameter_name, parameter_type in function_declaration.head.parameters:
            checker.context.variables[parameter_name] = parameter_type
        
        # Now check its body
        function_declaration.body = checker.check_body(function_declaration.body)
        
        # And finnaly submit it back
        function = Function(function_declaration)
        self.module.functions[function_declaration.head.name] = function

        return function

    def check(self, asts: Ast):
        for ast in asts:
            if type(ast) is Import:
                yield self.check_import(ast)
            elif type(ast) is StructDeclaration:
                yield self.check_struct_declaration(ast)
            elif type(ast) is UnionDeclaration:
                yield self.check_union_declaration(ast)
            elif type(ast) is Extern:
                yield self.check_extern(ast)
            elif type(ast) is FunctionDeclaration:
                yield self.check_function_declaration(ast)
            else:
                raise NotImplementedError(f"bug(checker): checking for {ast.format} is not implemented yet. at line {ast.line}, in module {self.module.name}")

        return
    
    @classmethod
    def new(cls, module: Module):
        return cls(module, Context(module, module.imports, module.functions, set()))
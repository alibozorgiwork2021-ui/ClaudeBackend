<?php

namespace Acme;

use Acme\Foo;

class Bar
{
    public function greet(): string
    {
        return (new Foo())->name();
    }
}
